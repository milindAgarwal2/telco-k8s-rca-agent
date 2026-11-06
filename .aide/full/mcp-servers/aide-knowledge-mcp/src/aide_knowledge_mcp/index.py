"""Deterministic, read-only indexing and retrieval for repository knowledge."""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .config import Settings

SourceTier = Literal["primary", "secondary"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]*")
_SPLIT_TOKEN_RE = re.compile(r"[_./:-]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b(?:glpat-|gldt-|gh[pousr]_|github_pat_|sk-|dp_)"
            r"[A-Za-z0-9._-]{8,}\b"
        ),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+"),
        r"\1[REDACTED_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)([\"']?(?:password|api[_-]?key|access[_-]?token|"
            r"personal[_-]?access[_-]?token)[\"']?\s*[:=]\s*[\"'])"
            r"([^\"']+)([\"'])"
        ),
        r"\1[REDACTED_VALUE]\3",
    ),
)


class KnowledgeError(ValueError):
    """Raised when a knowledge request violates the server contract."""


@dataclass(frozen=True)
class DocumentRecord:
    """One validated Markdown document inside an approved source boundary."""

    tier: SourceTier
    relative_path: str
    lines: tuple[str, ...]
    size_bytes: int
    modified_ns: int
    redactions: int


@dataclass(frozen=True)
class SectionRecord:
    """One line-addressable Markdown section or bounded section fragment."""

    tier: SourceTier
    relative_path: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    text: str
    token_counts: Counter[str]
    heading_tokens: frozenset[str]
    path_tokens: frozenset[str]


def _redact_sensitive(text: str) -> tuple[str, int]:
    redacted = text
    count = 0
    for pattern, replacement in _SECRET_PATTERNS:
        redacted, applied = pattern.subn(replacement, redacted)
        count += applied
    return redacted, count


def _tokenize(value: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(value):
        token = match.group(0).casefold().strip("./:-")
        if len(token) >= 2 and token not in _STOP_WORDS:
            tokens.append(token)
        for part in _SPLIT_TOKEN_RE.split(token):
            if len(part) >= 2 and part not in _STOP_WORDS and part != token:
                tokens.append(part)
    return tokens


def _source_label(tier: SourceTier) -> str:
    if tier == "primary":
        return "knowledge-base (primary)"
    return "OpenWiki (secondary)"


class KnowledgeIndex:
    """Lazy, thread-safe index over primary and secondary Markdown sources."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._signature = ""
        self._documents: dict[str, DocumentRecord] = {}
        self._sections: tuple[SectionRecord, ...] = ()
        self._document_frequency: Counter[str] = Counter()
        self._warnings: tuple[str, ...] = ()
        self._refreshed_at = ""

    def _discover_files(
        self,
    ) -> tuple[list[tuple[SourceTier, Path]], list[str]]:
        files: list[tuple[SourceTier, Path]] = []
        warnings: list[str] = []
        sources: tuple[tuple[SourceTier, Path], ...] = (
            ("primary", self.settings.primary_directory),
            ("secondary", self.settings.secondary_directory),
        )
        for tier, source_root in sources:
            if not source_root.is_dir():
                warnings.append(
                    f"{_source_label(tier)} directory is unavailable: "
                    f"{source_root.relative_to(self.settings.repository_root)}"
                )
                continue
            for candidate in sorted(source_root.rglob("*.md")):
                try:
                    if not candidate.is_file() or candidate.is_symlink():
                        continue
                    resolved = candidate.resolve(strict=True)
                except OSError as exc:
                    warnings.append(f"Skipped unreadable path {candidate}: {exc}")
                    continue
                if not resolved.is_relative_to(source_root):
                    warnings.append(f"Skipped path outside {source_root}: {candidate}")
                    continue
                if not resolved.is_relative_to(self.settings.repository_root):
                    warnings.append(f"Skipped path outside repository: {candidate}")
                    continue
                files.append((tier, resolved))
        return files, warnings

    def _calculate_signature(
        self,
        files: list[tuple[SourceTier, Path]],
    ) -> str:
        digest = hashlib.sha256()
        for tier, path in files:
            stat = path.stat()
            relative = path.relative_to(self.settings.repository_root).as_posix()
            digest.update(
                f"{tier}\0{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode()
            )
        return digest.hexdigest()

    def refresh(self, force: bool = False) -> bool:
        """Rebuild the in-memory index when source metadata changes.

        Args:
            force: Rebuild even when the source signature is unchanged.

        Returns:
            True when a new index was installed.
        """
        files, warnings = self._discover_files()
        signature = self._calculate_signature(files)
        with self._lock:
            if not force and signature == self._signature:
                return False

            documents: dict[str, DocumentRecord] = {}
            sections: list[SectionRecord] = []
            for tier, path in files:
                stat = path.stat()
                relative = path.relative_to(self.settings.repository_root).as_posix()
                if stat.st_size > self.settings.max_file_bytes:
                    warnings.append(
                        f"Skipped {relative}: {stat.st_size} bytes exceeds "
                        f"AIDE_KNOWLEDGE_MAX_FILE_BYTES"
                    )
                    continue
                try:
                    original = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    warnings.append(f"Skipped unreadable file {relative}: {exc}")
                    continue
                text, redactions = _redact_sensitive(original)
                lines = tuple(text.splitlines())
                document = DocumentRecord(
                    tier=tier,
                    relative_path=relative,
                    lines=lines,
                    size_bytes=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                    redactions=redactions,
                )
                documents[relative] = document
                sections.extend(self._build_sections(document))

            frequency: Counter[str] = Counter()
            for section in sections:
                frequency.update(section.token_counts.keys())

            self._documents = documents
            self._sections = tuple(sections)
            self._document_frequency = frequency
            self._warnings = tuple(warnings)
            self._signature = signature
            self._refreshed_at = datetime.now(timezone.utc).isoformat()
            return True

    def _build_sections(self, document: DocumentRecord) -> list[SectionRecord]:
        lines = document.lines
        if not lines:
            return []

        ranges: list[tuple[int, int, tuple[str, ...]]] = []
        heading_stack: list[str] = []
        current_heading: tuple[str, ...] = ()
        current_start = 0
        for index, line in enumerate(lines):
            match = _HEADING_RE.match(line)
            if not match:
                continue
            if index > current_start and any(
                item.strip() for item in lines[current_start:index]
            ):
                ranges.append((current_start, index, current_heading))
            level = len(match.group(1))
            title = match.group(2).strip().strip("#").strip()
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            current_heading = tuple(heading_stack)
            current_start = index

        if current_start < len(lines) and any(
            item.strip() for item in lines[current_start:]
        ):
            ranges.append((current_start, len(lines), current_heading))

        records: list[SectionRecord] = []
        for start, end, heading_path in ranges:
            for chunk_start, chunk_end in self._chunk_range(lines, start, end):
                text = "\n".join(lines[chunk_start:chunk_end]).strip()
                if not text:
                    continue
                effective_heading = heading_path or ("Document introduction",)
                records.append(
                    SectionRecord(
                        tier=document.tier,
                        relative_path=document.relative_path,
                        heading_path=effective_heading,
                        start_line=chunk_start + 1,
                        end_line=chunk_end,
                        text=text,
                        token_counts=Counter(_tokenize(text)),
                        heading_tokens=frozenset(
                            _tokenize(" ".join(effective_heading))
                        ),
                        path_tokens=frozenset(_tokenize(document.relative_path)),
                    )
                )
        return records

    def _chunk_range(
        self,
        lines: tuple[str, ...],
        start: int,
        end: int,
    ) -> list[tuple[int, int]]:
        chunks: list[tuple[int, int]] = []
        chunk_start = start
        characters = 0
        fence_marker = ""
        for index in range(start, end):
            line = lines[index]
            added = len(line) + 1
            if (
                index > chunk_start
                and characters + added > self.settings.max_section_chars
                and not fence_marker
            ):
                chunks.append((chunk_start, index))
                chunk_start = index
                characters = 0
            characters += added
            fence = _FENCE_RE.match(line)
            if fence:
                marker = fence.group(1)[0]
                fence_marker = "" if fence_marker == marker else marker
        if chunk_start < end:
            chunks.append((chunk_start, end))
        return chunks

    def _ensure_current(self) -> None:
        self.refresh(force=False)

    def _score(
        self,
        section: SectionRecord,
        query_counts: Counter[str],
        normalized_query: str,
    ) -> float:
        section_count = max(1, len(self._sections))
        score = 0.0
        matched = 0
        for token, query_frequency in query_counts.items():
            term_frequency = section.token_counts.get(token, 0)
            if term_frequency:
                matched += 1
                document_frequency = self._document_frequency.get(token, 0)
                inverse_frequency = (
                    math.log((section_count + 1) / (document_frequency + 1)) + 1.0
                )
                score += (
                    inverse_frequency
                    * (1.0 + math.log(term_frequency))
                    * min(query_frequency, 3)
                )
            if token in section.heading_tokens:
                score += 4.0
            if token in section.path_tokens:
                score += 3.0
        if query_counts:
            score += 3.0 * matched / len(query_counts)
        if len(normalized_query) >= 4 and normalized_query in section.text.casefold():
            score += 10.0
        return score

    def _excerpt(
        self,
        section: SectionRecord,
        query_tokens: frozenset[str],
    ) -> tuple[str, int, int]:
        lines = section.text.splitlines()
        if not lines:
            return "", section.start_line, section.start_line
        best_index = 0
        best_score = -1
        for index, line in enumerate(lines):
            line_tokens = set(_tokenize(line))
            score = len(line_tokens & query_tokens)
            if score > best_score:
                best_index = index
                best_score = score
        window_start = max(0, best_index - 3)
        window_end = min(len(lines), best_index + 7)
        excerpt_lines = lines[window_start:window_end]
        while (
            len("\n".join(excerpt_lines)) > self.settings.max_excerpt_chars
            and len(excerpt_lines) > 1
        ):
            if best_index - window_start > window_end - best_index - 1:
                window_start += 1
            else:
                window_end -= 1
            excerpt_lines = lines[window_start:window_end]
        excerpt = "\n".join(excerpt_lines)
        line_start = section.start_line + window_start
        line_end = line_start + len(excerpt_lines) - 1
        return excerpt, line_start, line_end

    def _result(
        self,
        section: SectionRecord,
        score: float,
        query_tokens: frozenset[str],
    ) -> dict[str, object]:
        excerpt, line_start, line_end = self._excerpt(section, query_tokens)
        return {
            "source_tier": section.tier,
            "source": _source_label(section.tier),
            "authority": (
                "primary design context"
                if section.tier == "primary"
                else "secondary generated explanation"
            ),
            "review_status": "draft unless explicitly reviewed by an SME",
            "path": section.relative_path,
            "heading": " / ".join(section.heading_path),
            "line_start": line_start,
            "line_end": line_end,
            "citation": f"{section.relative_path}:L{line_start}-L{line_end}",
            "score": round(score, 4),
            "excerpt": excerpt,
        }

    def search(
        self,
        query: str,
        limit: int = 12,
        include_secondary: bool = True,
    ) -> dict[str, object]:
        """Search both knowledge tiers while reserving priority for primary hits."""
        query = query.strip()
        if not query:
            raise KnowledgeError("query must not be empty")
        if len(query) > 2_000:
            raise KnowledgeError("query must not exceed 2000 characters")
        if not 1 <= limit <= 50:
            raise KnowledgeError("limit must be between 1 and 50")

        self._ensure_current()
        query_counts = Counter(_tokenize(query))
        if not query_counts:
            raise KnowledgeError("query must contain searchable terms")
        normalized_query = " ".join(query.casefold().split())
        ranked: dict[SourceTier, list[tuple[float, SectionRecord]]] = {
            "primary": [],
            "secondary": [],
        }
        with self._lock:
            for section in self._sections:
                score = self._score(section, query_counts, normalized_query)
                if score > 0:
                    ranked[section.tier].append((score, section))

        for matches in ranked.values():
            matches.sort(
                key=lambda item: (
                    -item[0],
                    item[1].relative_path,
                    item[1].start_line,
                )
            )

        primary_count = limit
        secondary_count = 0
        if include_secondary and ranked["secondary"]:
            preferred_primary = max(1, math.ceil(limit * 0.75))
            primary_count = min(len(ranked["primary"]), preferred_primary)
            secondary_count = min(
                len(ranked["secondary"]),
                limit - primary_count,
            )
            remaining = limit - primary_count - secondary_count
            if remaining:
                primary_count += min(
                    remaining,
                    len(ranked["primary"]) - primary_count,
                )
            remaining = limit - primary_count - secondary_count
            if remaining:
                secondary_count += min(
                    remaining,
                    len(ranked["secondary"]) - secondary_count,
                )
        else:
            primary_count = min(limit, len(ranked["primary"]))

        query_tokens = frozenset(query_counts)
        primary_results = [
            self._result(section, score, query_tokens)
            for score, section in ranked["primary"][:primary_count]
        ]
        secondary_results = [
            self._result(section, score, query_tokens)
            for score, section in ranked["secondary"][:secondary_count]
        ]
        return {
            "query": query,
            "source_policy": {
                "primary": "knowledge-base/",
                "secondary": "openwiki/",
                "rule": (
                    "Read primary results first. Secondary results may clarify "
                    "but never override primary evidence. Source code and tests "
                    "remain authoritative over both documentation tiers."
                ),
            },
            "primary_results": primary_results,
            "secondary_results": secondary_results,
            "result_count": len(primary_results) + len(secondary_results),
            "index_version": self._signature,
            "warnings": list(self._warnings),
        }

    def build_context(
        self,
        request: str,
        target_paths: list[str] | None = None,
        limit: int = 12,
        max_chars: int | None = None,
    ) -> dict[str, object]:
        """Build a bounded, precedence-labelled context package."""
        target_paths = target_paths or []
        if len(target_paths) > 20:
            raise KnowledgeError("target_paths must contain at most 20 entries")
        normalized_paths: list[str] = []
        for path in target_paths:
            normalized = path.strip().replace("\\", "/")
            if not normalized or len(normalized) > 500:
                raise KnowledgeError("each target path must contain 1-500 characters")
            normalized_paths.append(normalized)

        effective_query = request
        if normalized_paths:
            effective_query += "\nTarget paths: " + " ".join(normalized_paths)
        results = self.search(effective_query, limit, include_secondary=True)
        context_limit = max_chars or self.settings.max_context_chars
        if not 2_000 <= context_limit <= self.settings.max_context_chars:
            raise KnowledgeError(
                f"max_chars must be between 2000 and {self.settings.max_context_chars}"
            )

        rendered: list[str] = [
            "# AIDE knowledge context",
            "",
            (
                "Authority: source/tests > reviewed specifications > primary draft "
                "knowledge > secondary OpenWiki draft."
            ),
            "",
        ]
        truncated = False
        for key, heading in (
            ("primary_results", "## Primary: knowledge-base"),
            ("secondary_results", "## Secondary: OpenWiki"),
        ):
            candidates = results[key]
            if not isinstance(candidates, list) or not candidates:
                continue
            rendered.extend((heading, ""))
            for item in candidates:
                block = [
                    f"### {item['citation']} — {item['heading']}",
                    "",
                    str(item["excerpt"]),
                    "",
                ]
                proposed = "\n".join(rendered + block)
                if len(proposed) > context_limit:
                    truncated = True
                    break
                rendered.extend(block)

        return {
            "request": request,
            "target_paths": normalized_paths,
            "authority_order": [
                "repository source and schemas",
                "tests",
                "reviewed specifications",
                "knowledge-base drafts (primary)",
                "OpenWiki drafts (secondary)",
            ],
            "primary_context": results["primary_results"],
            "secondary_context": results["secondary_results"],
            "context_markdown": "\n".join(rendered).rstrip(),
            "truncated": truncated,
            "index_version": results["index_version"],
            "warnings": results["warnings"],
        }

    def _validated_document(self, relative_path: str) -> DocumentRecord:
        normalized = relative_path.strip().replace("\\", "/")
        if not normalized or len(normalized) > 1_000:
            raise KnowledgeError("relative_path must contain 1-1000 characters")
        requested = Path(normalized)
        if requested.is_absolute() or ".." in requested.parts:
            raise KnowledgeError("relative_path must not escape the repository")
        if requested.suffix.casefold() != ".md":
            raise KnowledgeError("only Markdown documents can be read")
        resolved = (self.settings.repository_root / requested).resolve()
        allowed = resolved.is_relative_to(
            self.settings.primary_directory
        ) or resolved.is_relative_to(self.settings.secondary_directory)
        if not allowed:
            raise KnowledgeError(
                "relative_path must be under knowledge-base/ or openwiki/"
            )
        canonical = resolved.relative_to(self.settings.repository_root).as_posix()
        self._ensure_current()
        document = self._documents.get(canonical)
        if document is None:
            raise KnowledgeError(f"document is unavailable or not indexed: {canonical}")
        return document

    def read_document(
        self,
        relative_path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, object]:
        """Read a bounded line range from an approved Markdown document."""
        document = self._validated_document(relative_path)
        line_count = len(document.lines)
        if not 1 <= start_line <= max(1, line_count):
            raise KnowledgeError("start_line is outside the document")
        effective_end = end_line or min(
            line_count,
            start_line + self.settings.max_read_lines - 1,
        )
        if effective_end < start_line or effective_end > line_count:
            raise KnowledgeError("end_line is outside the requested document range")
        if effective_end - start_line + 1 > self.settings.max_read_lines:
            raise KnowledgeError(
                f"a read may return at most {self.settings.max_read_lines} lines"
            )
        content = "\n".join(document.lines[start_line - 1 : effective_end])
        return {
            "source_tier": document.tier,
            "source": _source_label(document.tier),
            "path": document.relative_path,
            "line_start": start_line,
            "line_end": effective_end,
            "line_count": line_count,
            "citation": (f"{document.relative_path}:L{start_line}-L{effective_end}"),
            "content": content,
            "redactions_applied_to_document": document.redactions,
        }

    def list_documents(
        self,
        source: Literal["all", "primary", "secondary"] = "all",
        prefix: str = "",
        limit: int = 200,
    ) -> dict[str, object]:
        """List indexed documents without returning document bodies."""
        if source not in {"all", "primary", "secondary"}:
            raise KnowledgeError("source must be all, primary, or secondary")
        if not 1 <= limit <= 500:
            raise KnowledgeError("limit must be between 1 and 500")
        normalized_prefix = prefix.strip().replace("\\", "/").casefold()
        self._ensure_current()
        documents: list[dict[str, object]] = []
        for record in sorted(
            self._documents.values(),
            key=lambda item: (item.tier, item.relative_path),
        ):
            if source != "all" and record.tier != source:
                continue
            if normalized_prefix and not record.relative_path.casefold().startswith(
                normalized_prefix
            ):
                continue
            documents.append(
                {
                    "source_tier": record.tier,
                    "source": _source_label(record.tier),
                    "path": record.relative_path,
                    "line_count": len(record.lines),
                    "size_bytes": record.size_bytes,
                    "modified_utc": datetime.fromtimestamp(
                        record.modified_ns / 1_000_000_000,
                        tz=timezone.utc,
                    ).isoformat(),
                    "redactions": record.redactions,
                }
            )
            if len(documents) >= limit:
                break
        return {
            "source": source,
            "prefix": prefix,
            "documents": documents,
            "returned": len(documents),
            "index_version": self._signature,
        }

    def status(self) -> dict[str, object]:
        """Return source health, counts, limits, and the current index version."""
        self._ensure_current()
        primary_documents = sum(
            record.tier == "primary" for record in self._documents.values()
        )
        secondary_documents = sum(
            record.tier == "secondary" for record in self._documents.values()
        )
        primary_sections = sum(section.tier == "primary" for section in self._sections)
        secondary_sections = sum(
            section.tier == "secondary" for section in self._sections
        )
        return {
            "server": "aide-knowledge-mcp",
            "mode": "local read-only lexical retrieval",
            "repository_root": self.settings.repository_root.as_posix(),
            "sources": {
                "primary": {
                    "path": self.settings.primary_directory.relative_to(
                        self.settings.repository_root
                    ).as_posix(),
                    "available": self.settings.primary_directory.is_dir(),
                    "documents": primary_documents,
                    "sections": primary_sections,
                },
                "secondary": {
                    "path": self.settings.secondary_directory.relative_to(
                        self.settings.repository_root
                    ).as_posix(),
                    "available": self.settings.secondary_directory.is_dir(),
                    "documents": secondary_documents,
                    "sections": secondary_sections,
                },
            },
            "limits": {
                "max_file_bytes": self.settings.max_file_bytes,
                "max_section_chars": self.settings.max_section_chars,
                "max_excerpt_chars": self.settings.max_excerpt_chars,
                "max_read_lines": self.settings.max_read_lines,
                "max_context_chars": self.settings.max_context_chars,
            },
            "index_version": self._signature,
            "refreshed_at": self._refreshed_at,
            "warnings": list(self._warnings),
        }
