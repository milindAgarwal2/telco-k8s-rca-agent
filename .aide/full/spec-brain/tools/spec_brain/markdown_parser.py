"""Deterministic Markdown and OpenWiki Knowledge Format parsing."""

from __future__ import annotations

import ast
import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.spec_brain.models import normalize_relative_path

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
_MARKDOWN_LINK_RE = re.compile(r"\[[^]]*]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)")
_REPOSITORY_RESOURCE_RE = re.compile(r"repo://([^\s)#]+)(?:#L\d+(?:-L\d+)?)?")
_INLINE_PATH_RE = re.compile(
    r"(?<![\w.-])((?:\.{0,2}/)?(?:[\w.-]+/)+[\w.-]+\."
    r"(?:py|pyi|c|cc|cpp|cu|cuh|h|hpp|rs|sh|toml|ya?ml|json|sql|"
    r"proto|md|txt))(?:#L\d+(?:-L\d+)?)?"
)


@dataclass(frozen=True)
class MarkdownSection:
    """A complete Markdown section whose tables and fences remain intact."""

    level: int
    title: str
    heading_path: tuple[str, ...]
    body: str
    start_line: int
    end_line: int
    slug: str


@dataclass(frozen=True)
class MarkdownTable:
    """A Markdown table captured within one semantic section."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ParsedMarkdown:
    """Front matter and section-level representation of one Markdown file."""

    frontmatter: dict[str, Any]
    sections: tuple[MarkdownSection, ...]


def slugify(value: str) -> str:
    """Create a stable GitHub-like ASCII fragment for an identifier."""

    value = re.sub(r"<[^>]+>", "", value).lower()
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "section"


def parse_markdown(text: str) -> ParsedMarkdown:
    """Parse Markdown without splitting fenced blocks or tables.

    Each heading begins one record and the record continues to the next heading.
    This deliberately leaves every contiguous table, list, and Mermaid fence in
    the same record as its owning heading.
    """

    frontmatter, body, body_start_line = split_frontmatter(text)
    lines = body.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    fence_character: str | None = None
    fence_length = 0

    for index, line in enumerate(lines):
        fence = _FENCE_RE.match(line.rstrip("\r\n"))
        if fence:
            marker = fence.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None:
            continue
        heading = _HEADING_RE.match(line.rstrip("\r\n"))
        if heading:
            title = heading.group(2).strip()
            headings.append((index, len(heading.group(1)), title))

    if not headings:
        stripped = body.strip()
        if not stripped:
            return ParsedMarkdown(frontmatter, ())
        return ParsedMarkdown(
            frontmatter,
            (
                MarkdownSection(
                    level=0,
                    title="Document",
                    heading_path=("Document",),
                    body=stripped + "\n",
                    start_line=body_start_line,
                    end_line=body_start_line + len(lines) - 1,
                    slug="document",
                ),
            ),
        )

    sections: list[MarkdownSection] = []
    stack: list[tuple[int, str]] = []
    occurrences: dict[str, int] = {}
    for heading_index, (line_index, level, title) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        heading_path = tuple(item[1] for item in stack)
        base_slug = "/".join(slugify(item) for item in heading_path)
        occurrence = occurrences.get(base_slug, 0) + 1
        occurrences[base_slug] = occurrence
        slug = base_slug if occurrence == 1 else f"{base_slug}-{occurrence}"
        next_line = (
            headings[heading_index + 1][0]
            if heading_index + 1 < len(headings)
            else len(lines)
        )
        section_body = "".join(lines[line_index:next_line]).rstrip() + "\n"
        sections.append(
            MarkdownSection(
                level=level,
                title=title,
                heading_path=heading_path,
                body=section_body,
                start_line=body_start_line + line_index,
                end_line=body_start_line + next_line - 1,
                slug=slug,
            )
        )
    return ParsedMarkdown(frontmatter, tuple(sections))


def split_frontmatter(text: str) -> tuple[dict[str, Any], str, int]:
    """Split and minimally parse an OpenWiki YAML front-matter block."""

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text, 1
    closing = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing is None:
        raise ValueError("front matter starts with '---' but has no closing delimiter")
    raw = "".join(lines[1:closing])
    return parse_simple_yaml(raw), "".join(lines[closing + 1 :]), closing + 2


def parse_simple_yaml(raw: str) -> dict[str, Any]:
    """Parse the small YAML subset used by current OpenWiki front matter.

    The supported subset is intentionally narrow: top-level scalars, inline
    mappings, and lists of scalars or mappings. Unsupported indentation fails
    closed instead of producing misleading metadata.
    """

    result: dict[str, Any] = {}
    active_list: list[Any] | None = None
    active_item: dict[str, Any] | None = None
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0:
            if ":" not in line:
                raise ValueError(f"unsupported front-matter line {line_number}")
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            active_item = None
            if not value:
                active_list = []
                result[key] = active_list
            else:
                active_list = None
                result[key] = _parse_yaml_scalar(value)
            continue
        if indent == 2 and line.startswith("- ") and active_list is not None:
            item = line[2:].strip()
            if ":" in item:
                key, value = item.split(":", 1)
                active_item = {key.strip(): _parse_yaml_scalar(value.strip())}
                active_list.append(active_item)
            else:
                active_item = None
                active_list.append(_parse_yaml_scalar(item))
            continue
        if indent >= 4 and active_item is not None and ":" in line:
            key, value = line.split(":", 1)
            active_item[key.strip()] = _parse_yaml_scalar(value.strip())
            continue
        raise ValueError(f"unsupported front-matter indentation at line {line_number}")
    return result


def _parse_yaml_scalar(value: str) -> Any:
    if not value:
        return None
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if value.startswith("{") and value.endswith("}"):
        entries = _split_table_cells(value[1:-1], delimiter=",")
        parsed: dict[str, Any] = {}
        for entry in entries:
            if ":" not in entry:
                raise ValueError(f"invalid inline mapping entry: {entry!r}")
            key, item = entry.split(":", 1)
            parsed[key.strip()] = _parse_yaml_scalar(item.strip())
        return parsed
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def iter_markdown_tables(body: str) -> Iterable[MarkdownTable]:
    """Yield simple Markdown tables from a section body."""

    lines = body.splitlines()
    index = 0
    while index + 1 < len(lines):
        headers = _table_cells(lines[index])
        separator = _table_cells(lines[index + 1])
        if headers and _is_table_separator(separator, len(headers)):
            rows: list[tuple[str, ...]] = []
            index += 2
            while index < len(lines):
                cells = _table_cells(lines[index])
                if not cells or len(cells) != len(headers):
                    break
                rows.append(tuple(cells))
                index += 1
            yield MarkdownTable(tuple(headers), tuple(rows))
            continue
        index += 1


def document_metadata(parsed: ParsedMarkdown) -> dict[str, str]:
    """Extract two-column document-control and specification metadata rows."""

    metadata: dict[str, str] = {}
    for section in parsed.sections:
        title = section.title.lower()
        if "metadata" not in title and "control" not in title:
            continue
        for table in iter_markdown_tables(section.body):
            if len(table.headers) != 2:
                continue
            for key, value in table.rows:
                metadata[_plain_cell(key).lower()] = _plain_cell(value)
    return metadata


def extract_repository_references(
    body: str,
    source_relative_path: str,
    repository_root: Path | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Extract normalized source and test paths mentioned by a section."""

    candidates: set[str] = set()
    candidates.update(
        match.group(1) for match in _REPOSITORY_RESOURCE_RE.finditer(body)
    )
    for match in _MARKDOWN_LINK_RE.finditer(body):
        candidates.add(match.group(1) or match.group(2))
    candidates.update(match.group(1) for match in _INLINE_PATH_RE.finditer(body))

    paths: set[str] = set()
    tests: set[str] = set()
    source_directory = posixpath.dirname(source_relative_path.replace("\\", "/"))
    for candidate in candidates:
        resolved = _resolve_repository_reference(
            candidate, source_directory, repository_root
        )
        if resolved is None:
            continue
        if repository_root is not None and not (repository_root / resolved).exists():
            continue
        if resolved.startswith("tests/") or "/tests/" in f"/{resolved}":
            tests.add(resolved)
        else:
            paths.add(resolved)
    return tuple(sorted(paths)), tuple(sorted(tests))


def parse_link_cell(cell: str) -> tuple[str, str | None]:
    """Return visible text and link target from a relationship-map cell."""

    match = re.search(r"\[([^]]+)]\((?:<([^>]+)>|([^\s)]+))\)", cell)
    if match:
        return _plain_cell(match.group(1)), match.group(2) or match.group(3)
    return _plain_cell(cell), None


def _resolve_repository_reference(
    raw: str,
    source_directory: str,
    repository_root: Path | None = None,
) -> str | None:
    value = raw.strip().strip("<>")
    if not value or value.startswith(("#", "http://", "https://", "mailto:")):
        return None
    if value.startswith("repo://"):
        value = value[7:]
        base = ""
    else:
        root_candidate = value.split("#", 1)[0].split("?", 1)[0]
        is_explicit_relative = root_candidate.startswith(("./", "../"))
        if (
            repository_root is not None
            and not is_explicit_relative
            and (repository_root / root_candidate).exists()
        ):
            base = ""
        else:
            base = source_directory
    value = value.split("#", 1)[0].split("?", 1)[0]
    if not value:
        return None
    combined = posixpath.normpath(posixpath.join(base, value))
    try:
        return normalize_relative_path(combined)
    except ValueError:
        return None


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return _split_table_cells(stripped[1:-1])


def _split_table_cells(value: str, delimiter: str = "|") -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    in_code = False
    for character in value:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            current.append(character)
            escaped = True
        elif character == "`":
            current.append(character)
            in_code = not in_code
        elif character == delimiter and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    cells.append("".join(current).strip())
    return cells


def _is_table_separator(cells: list[str], expected: int) -> bool:
    return len(cells) == expected and all(
        re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells
    )


def _plain_cell(cell: str) -> str:
    value = re.sub(r"<br\s*/?>", "; ", cell, flags=re.IGNORECASE)
    value = re.sub(r"\[([^]]+)]\((?:<[^>]+>|[^)]+)\)", r"\1", value)
    return value.strip().strip("`")
