"""Specification-focused composition over local repository evidence."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Literal, cast

from aide_architecture_mcp.service import ArchitectureService
from aide_knowledge_mcp.index import KnowledgeError

from .config import SpecSettings

SpecArtifact = Literal["requirements", "design", "tasks", "all"]

_ARTIFACT_TERMS: dict[SpecArtifact, str] = {
    "requirements": (
        "user outcome scope requirements acceptance criteria EARS behavior "
        "failure compatibility"
    ),
    "design": (
        "current architecture proposed design components interfaces data contracts "
        "errors ownership tests"
    ),
    "tasks": (
        "implementation tasks dependencies sequencing verification tests rollout "
        "traceability"
    ),
    "all": (
        "requirements design tasks acceptance architecture contracts traceability "
        "verification"
    ),
}

_CHECKLISTS: dict[SpecArtifact, list[str]] = {
    "requirements": [
        "separate desired behavior from verified current behavior",
        "assign stable identifiers to atomic requirements",
        "use Easy Approach to Requirements Syntax where it improves precision",
        "make acceptance scenarios observable and testable",
        "record goals, non-goals, compatibility, failures, and unknowns",
        "map each story outcome and acceptance criterion to requirements",
    ],
    "design": [
        "cite exact current components, paths, symbols, and tests",
        "define inputs, outputs, contracts, ownership, and interaction points",
        "show current and proposed flows without inventing runtime calls",
        "define exception translation, cleanup, recovery, and diagnostics",
        "record alternatives, decisions, assumptions, and unresolved questions",
        "map every design element to requirements and verification evidence",
    ],
    "tasks": [
        "order work by dependency and keep tasks independently verifiable",
        "map every task to requirements and design elements",
        "name exact likely files only when supported by evidence",
        "include focused tests and documentation reconciliation",
        "avoid unrelated refactoring, modernization, and speculative work",
        "keep implementation tasks distinct from review or decision gates",
    ],
    "all": [
        "keep requirements, design, and tasks mutually traceable",
        "preserve the evidence authority and conflict-resolution model",
        "label direct evidence, inference, proposals, and unknowns",
        "inspect current source and focused tests before normative claims",
        "treat all generated documents as drafts until maintainer review",
        "do not implement the feature during specification generation",
    ],
}

_REQUIRED_HEADINGS: dict[SpecArtifact, tuple[str, ...]] = {
    "requirements": (
        "authority",
        "goals",
        "non-goals",
        "requirements",
        "acceptance criteria",
        "traceability",
        "unresolved",
    ),
    "design": (
        "evidence",
        "current",
        "proposed",
        "interfaces",
        "error",
        "testing",
        "traceability",
        "unresolved",
    ),
    "tasks": (
        "task",
        "dependencies",
        "verification",
        "traceability",
    ),
    "all": (),
}

_EVIDENCE_LABELS = (
    "STORY",
    "KB",
    "FSPEC",
    "SRC",
    "TEST",
    "OW",
    "INFERENCE",
    "PROPOSED",
    "DECISION-NEEDED",
    "ASSUMPTION",
    "UNKNOWN",
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

_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,15}-\d{2,5}\b")
_IDENTIFIER_DEFINITION_RE = re.compile(
    r"(?m)^\s*(?:#{1,6}\s+|[-*]\s+)?(?:\*\*)?"
    r"([A-Z][A-Z0-9]{1,15}-\d{2,5})(?:\*\*)?\s*(?::|—|-)"
)
_EARS_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?"
    r"(?:[A-Z][A-Z0-9]{1,15}-\d{2,5}\s*:\s*)?"
    r"(?:(?:WHEN|WHILE|WHERE)\b.*"
    r"\bTHE SYSTEM SHALL\b|IF\b.*\bTHEN THE SYSTEM SHALL\b|"
    r"THE SYSTEM SHALL\b)"
)


class SpecError(KnowledgeError):
    """Raised when a specification request violates the server contract."""


def _redact_sensitive(text: str) -> tuple[str, int]:
    redacted = text
    count = 0
    for pattern, replacement in _SECRET_PATTERNS:
        redacted, applied = pattern.subn(replacement, redacted)
        count += applied
    return redacted, count


class SpecificationService:
    """Prepare evidence packets and mechanical specification diagnostics."""

    def __init__(
        self,
        settings: SpecSettings,
        architecture: ArchitectureService,
    ) -> None:
        self.settings = settings
        self.architecture = architecture

    @staticmethod
    def _artifact(value: str) -> SpecArtifact:
        if value not in {"requirements", "design", "tasks", "all"}:
            raise SpecError("artifact must be requirements, design, tasks, or all")
        return cast(SpecArtifact, value)

    def _repository_path(self, relative_path: str) -> tuple[str, Path]:
        normalized = relative_path.strip().replace("\\", "/")
        if not normalized or len(normalized) > 1_000:
            raise SpecError("relative_path must contain 1-1000 characters")
        requested = Path(normalized)
        if requested.is_absolute() or ".." in requested.parts:
            raise SpecError("relative_path must not escape the repository")
        resolved = (self.settings.repository_root / requested).resolve()
        if not resolved.is_relative_to(self.settings.repository_root):
            raise SpecError("relative_path must resolve inside the repository")
        canonical = resolved.relative_to(self.settings.repository_root).as_posix()
        return canonical, resolved

    def _is_local_spec_input(self, path: Path) -> bool:
        if path.suffix.casefold() != ".md":
            return False
        if path.is_relative_to(self.settings.story_directory):
            return True
        if path.name.casefold() == "specs.md":
            return True
        kiro_specs = self.settings.repository_root / ".kiro" / "specs"
        allowed_names = {"requirements.md", "design.md", "tasks.md"}
        return path.is_relative_to(kiro_specs) and path.name in allowed_names

    def _read_local_document(
        self,
        relative_path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, object]:
        canonical, resolved = self._repository_path(relative_path)
        if not self._is_local_spec_input(resolved):
            raise SpecError(
                "local reads are limited to Jira-style Markdown, folder "
                "SPECS.md files, and existing Kiro specification documents"
            )
        if not resolved.is_file() or resolved.is_symlink():
            raise SpecError(f"document is unavailable: {canonical}")
        size_bytes = resolved.stat().st_size
        if size_bytes > self.settings.max_story_bytes:
            raise SpecError(f"document exceeds {self.settings.max_story_bytes} bytes")
        original = resolved.read_text(encoding="utf-8", errors="replace")
        text, redactions = _redact_sensitive(original)
        lines = text.splitlines()
        if not lines:
            raise SpecError(f"document is empty: {canonical}")
        if not 1 <= start_line <= len(lines):
            raise SpecError("start_line is outside the document")
        effective_end = end_line or min(
            len(lines),
            start_line + self.settings.max_read_lines - 1,
        )
        if effective_end < start_line or effective_end > len(lines):
            raise SpecError("end_line is outside the document")
        if effective_end - start_line + 1 > self.settings.max_read_lines:
            raise SpecError(
                f"a read may return at most {self.settings.max_read_lines} lines"
            )
        return {
            "source_tier": "requirement_input_or_folder_contract",
            "path": canonical,
            "line_start": start_line,
            "line_end": effective_end,
            "line_count": len(lines),
            "citation": f"{canonical}:L{start_line}-L{effective_end}",
            "content": "\n".join(lines[start_line - 1 : effective_end]),
            "truncated": effective_end < len(lines),
            "redactions_applied_to_document": redactions,
        }

    def status(self) -> dict[str, object]:
        """Return source health and the specification assistance contract."""
        architecture_status = self.architecture.status()
        story_count = 0
        if self.settings.story_directory.is_dir():
            story_count = sum(
                path.is_file() and not path.is_symlink()
                for path in self.settings.story_directory.rglob("*.md")
            )
        return {
            "server": "aide-spec-mcp",
            "mode": "local read-only specification evidence and validation",
            "supported_artifacts": ["requirements", "design", "tasks"],
            "story_source": {
                "path": self.settings.story_directory.relative_to(
                    self.settings.repository_root
                ).as_posix(),
                "documents": story_count,
            },
            "knowledge_sources": architecture_status["sources"],
            "folder_spec_resolution": (
                "existing SPECS.md files along explicitly targeted ancestor paths"
            ),
            "generation_mode": (
                "context and mechanical checks only; no repository writes"
            ),
            "limits": {
                "max_story_bytes": self.settings.max_story_bytes,
                "max_read_lines": self.settings.max_read_lines,
                "max_document_chars": self.settings.max_document_chars,
                "max_context_chars": (
                    self.settings.architecture.knowledge.max_context_chars
                ),
            },
            "index_version": architecture_status["index_version"],
            "warnings": architecture_status["warnings"],
        }

    def list_stories(self, limit: int = 100) -> dict[str, object]:
        """List available local Jira-style Markdown inputs without bodies."""
        if not 1 <= limit <= 200:
            raise SpecError("limit must be between 1 and 200")
        documents: list[dict[str, object]] = []
        if self.settings.story_directory.is_dir():
            for path in sorted(self.settings.story_directory.rglob("*.md")):
                if not path.is_file() or path.is_symlink():
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(self.settings.story_directory):
                    continue
                stat = resolved.stat()
                documents.append(
                    {
                        "path": resolved.relative_to(
                            self.settings.repository_root
                        ).as_posix(),
                        "size_bytes": stat.st_size,
                    }
                )
                if len(documents) >= limit:
                    break
        return {
            "stories": documents,
            "returned": len(documents),
            "authority": (
                "desired-behavior input; proposed technical details still require "
                "repository verification"
            ),
        }

    def resolve_folder_specs(
        self,
        target_paths: list[str],
    ) -> dict[str, object]:
        """Resolve existing ancestor SPECS.md contracts for target paths."""
        if not target_paths or len(target_paths) > 20:
            raise SpecError("target_paths must contain between 1 and 20 entries")
        matches: dict[str, dict[str, object]] = {}
        normalized_targets: list[str] = []
        for value in target_paths:
            canonical, resolved = self._repository_path(value)
            normalized_targets.append(canonical)
            cursor = resolved
            if resolved.is_file() or (not resolved.exists() and resolved.suffix):
                cursor = resolved.parent
            while cursor.is_relative_to(self.settings.repository_root):
                candidate = cursor / "SPECS.md"
                if candidate.is_file() and not candidate.is_symlink():
                    relative = candidate.relative_to(
                        self.settings.repository_root
                    ).as_posix()
                    if relative not in matches:
                        matches[relative] = {
                            "path": relative,
                            "citation": relative,
                            "role": "folder contract requiring source verification",
                        }
                if cursor == self.settings.repository_root:
                    break
                cursor = cursor.parent
        return {
            "target_paths": normalized_targets,
            "folder_specifications": list(matches.values()),
            "returned": len(matches),
            "rule": (
                "Use folder specifications for navigation and declared contracts; "
                "verify normative current behavior in source and focused tests."
            ),
        }

    def search(
        self,
        query: str,
        artifact: str = "all",
        target_paths: list[str] | None = None,
        limit: int = 16,
    ) -> dict[str, object]:
        """Search evidence using terminology appropriate to one artifact."""
        selected = self._artifact(artifact)
        if not query.strip():
            raise SpecError("query must not be empty")
        enriched = f"{query}\nSpecification focus: {_ARTIFACT_TERMS[selected]}"
        level = "lld" if selected == "tasks" else "both"
        result = self.architecture.search(
            enriched,
            level=level,
            target_paths=target_paths,
            limit=limit,
        )
        result.update(
            {
                "artifact": selected,
                "specification_checklist": _CHECKLISTS[selected],
                "evidence_labels": list(_EVIDENCE_LABELS),
            }
        )
        return result

    def build_context(
        self,
        request: str,
        artifact: str = "all",
        story_path: str | None = None,
        target_paths: list[str] | None = None,
        limit: int = 18,
        max_chars: int | None = None,
    ) -> dict[str, object]:
        """Build a bounded packet for Kiro requirements, design, or tasks."""
        selected = self._artifact(artifact)
        request = request.strip()
        if not request or len(request) > 10_000:
            raise SpecError("request must contain 1-10000 characters")
        context_limit = (
            max_chars or self.settings.architecture.knowledge.max_context_chars
        )
        if (
            not 2_000
            <= context_limit
            <= (self.settings.architecture.knowledge.max_context_chars)
        ):
            raise SpecError(
                "max_chars is outside the configured specification context limit"
            )

        story = self._read_local_document(story_path) if story_path else None
        paths = target_paths or []
        folder_specs = (
            self.resolve_folder_specs(paths)
            if paths
            else {
                "target_paths": [],
                "folder_specifications": [],
                "returned": 0,
            }
        )
        level = "lld" if selected == "tasks" else "both"
        architecture_context = self.architecture.build_context(
            f"{request}\nSpecification focus: {_ARTIFACT_TERMS[selected]}",
            level=level,
            target_paths=paths,
            limit=limit,
            max_chars=context_limit,
        )

        rendered = [
            "# AIDE specification context",
            "",
            "## Authority and use",
            "",
            (
                "The request or story defines desired behavior. Source, schemas, "
                "and tests establish current behavior. Reviewed specifications "
                "outrank drafts. OpenWiki is secondary discovery context."
            ),
            "",
        ]
        if story:
            rendered.extend(
                [
                    f"## Requirement input — {story['citation']}",
                    "",
                    str(story["content"]),
                    "",
                ]
            )
        specifications = folder_specs["folder_specifications"]
        if isinstance(specifications, list) and specifications:
            rendered.extend(["## Relevant folder contracts", ""])
            rendered.extend(f"- {item['path']}" for item in specifications)
            rendered.append("")
        rendered.extend(
            [
                "## Primary and secondary design evidence",
                "",
                str(architecture_context["context_markdown"]),
                "",
                "## Artifact checklist",
                "",
            ]
        )
        rendered.extend(f"- {item}" for item in _CHECKLISTS[selected])
        markdown = "\n".join(rendered).rstrip()
        truncated = bool(architecture_context.get("truncated"))
        if len(markdown) > context_limit:
            markdown = markdown[:context_limit].rstrip()
            truncated = True

        return {
            "request": request,
            "artifact": selected,
            "story_evidence": story,
            "folder_specifications": specifications,
            "architecture_context": architecture_context,
            "authority_model": {
                "desired_behavior": "accepted user request or Jira-style story",
                "current_behavior": "source, schemas, configuration, and tests",
                "supporting_context": (
                    "reviewed specifications, knowledge-base drafts, then OpenWiki"
                ),
                "conflict_rule": (
                    "record conflicts; do not rewrite desired behavior to match "
                    "current behavior or describe desired behavior as implemented"
                ),
            },
            "evidence_labels": list(_EVIDENCE_LABELS),
            "specification_checklist": _CHECKLISTS[selected],
            "ears_patterns": [
                "THE SYSTEM SHALL <response>",
                "WHEN <trigger>, THE SYSTEM SHALL <response>",
                "WHILE <state>, THE SYSTEM SHALL <response>",
                "WHERE <feature>, THE SYSTEM SHALL <response>",
                "IF <condition>, THEN THE SYSTEM SHALL <response>",
            ],
            "context_markdown": markdown,
            "truncated": truncated,
            "draft_notice": (
                "Generated specifications remain drafts until responsible "
                "maintainers or subject-matter experts review them."
            ),
        }

    def traceability_plan(
        self,
        request: str,
        story_path: str | None = None,
        target_paths: list[str] | None = None,
        limit: int = 16,
    ) -> dict[str, object]:
        """Return evidence anchors and matrix columns for traceable specs."""
        result = self.search(request, "all", target_paths, limit)
        primary = result.get("primary_results", [])
        secondary = result.get("secondary_results", [])
        story = self._read_local_document(story_path) if story_path else None
        folder_specs = (
            self.resolve_folder_specs(target_paths)["folder_specifications"]
            if target_paths
            else []
        )
        return {
            "story_citation": story["citation"] if story else None,
            "folder_specifications": folder_specs,
            "primary_evidence_citations": [
                item["citation"] for item in primary if "citation" in item
            ],
            "secondary_evidence_citations": [
                item["citation"] for item in secondary if "citation" in item
            ],
            "required_mappings": [
                "story outcome or acceptance criterion -> requirement",
                "requirement -> design element",
                "design element -> implementation task",
                "requirement -> verification evidence",
                "unresolved decision -> accountable review gate",
            ],
            "matrix_columns": [
                "source",
                "requirement_id",
                "design_id",
                "task_id",
                "verification",
                "status",
            ],
            "warning": (
                "Retrieved documentation identifies investigation targets; Kiro "
                "must verify current behavior in source and focused tests."
            ),
        }

    def assess_document(
        self,
        markdown: str,
        artifact: str,
    ) -> dict[str, object]:
        """Run objective draft checks without judging specification quality."""
        selected = self._artifact(artifact)
        if selected == "all":
            raise SpecError("assessment requires one concrete artifact type")
        if not markdown.strip():
            raise SpecError("markdown must not be empty")
        if len(markdown) > self.settings.max_document_chars:
            raise SpecError(
                f"markdown exceeds {self.settings.max_document_chars} characters"
            )

        headings = [match.group(1).strip() for match in _HEADING_RE.finditer(markdown)]
        folded_headings = [heading.casefold() for heading in headings]
        missing_headings = [
            expected
            for expected in _REQUIRED_HEADINGS[selected]
            if not any(expected in heading for heading in folded_headings)
        ]
        identifiers = _IDENTIFIER_RE.findall(markdown)
        definitions = _IDENTIFIER_DEFINITION_RE.findall(markdown)
        counts = Counter(definitions)
        duplicates = sorted(
            identifier for identifier, count in counts.items() if count > 1
        )
        evidence_counts = {
            label: markdown.count(f"[{label}]") for label in _EVIDENCE_LABELS
        }
        warnings: list[str] = []
        ears_count = len(_EARS_RE.findall(markdown))
        if selected == "requirements" and ears_count == 0:
            warnings.append("No EARS-form requirement statement was detected.")
        if not definitions:
            warnings.append("No stable specification definitions were detected.")
        if not any(evidence_counts.values()):
            warnings.append("No recognized evidence labels were detected.")
        if missing_headings:
            warnings.append("One or more expected topic headings are absent.")

        return {
            "artifact": selected,
            "mechanical_only": True,
            "heading_count": len(headings),
            "missing_heading_topics": missing_headings,
            "identifier_reference_count": len(identifiers),
            "identifier_definition_count": len(definitions),
            "duplicate_identifiers": duplicates,
            "ears_statement_count": ears_count,
            "evidence_label_counts": evidence_counts,
            "has_draft_marker": "draft" in markdown.casefold(),
            "has_unresolved_marker": any(
                term in markdown.casefold()
                for term in ("unresolved", "unknown", "decision-needed")
            ),
            "warnings": warnings,
            "quality_notice": (
                "Passing mechanical checks does not establish correctness, "
                "completeness, or maintainer approval."
            ),
        }

    def read_evidence(
        self,
        relative_path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, object]:
        """Read approved specification input or knowledge evidence."""
        canonical, resolved = self._repository_path(relative_path)
        knowledge = self.settings.architecture.knowledge
        if resolved.is_relative_to(
            knowledge.primary_directory
        ) or resolved.is_relative_to(knowledge.secondary_directory):
            return self.architecture.read_evidence(
                canonical,
                start_line,
                end_line,
            )
        return self._read_local_document(canonical, start_line, end_line)

    def refresh(self) -> dict[str, object]:
        """Refresh only the in-memory documentation index."""
        result = self.architecture.refresh()
        return {
            "server": "aide-spec-mcp",
            "rebuilt": result["rebuilt"],
            "index_version": result["index_version"],
            "warnings": result["warnings"],
        }
