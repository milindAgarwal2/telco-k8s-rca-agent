"""Compose bounded, authority-ordered context packages for Kiro."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from tools.spec_brain.graphiti_loader import SemanticFact
from tools.spec_brain.retrieval import ExactContext


class ContextBudgetError(RuntimeError):
    """Raised when useful primary context cannot fit the configured limit."""


def compose_context(
    request: str,
    exact: ExactContext,
    semantic_facts: Iterable[SemanticFact],
    *,
    mode: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Compose a predictable context package in specification-authority order."""

    if mode not in {"requirements", "design", "tasks", "all"}:
        raise ValueError(f"unsupported specification mode: {mode}")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than zero")

    primary = list(_dedupe_records(exact.primary_context))
    secondary = list(_dedupe_records(exact.secondary_context))
    primary_ids = {record.get("stable_id") for record in primary}
    primary_text = {_normalized_record_text(record) for record in primary}
    secondary = [
        record
        for record in secondary
        if record.get("stable_id") not in primary_ids
        and _normalized_record_text(record) not in primary_text
    ]
    semantic = list(_dedupe_semantic(semantic_facts))

    package: dict[str, Any] = {
        "request": request,
        "mode": mode,
        "authority_order": [
            "primary knowledge-base and folder specifications",
            "exact Neo4j relationships",
            "repository source and tests",
            "Graphiti semantic context",
            "secondary OpenWiki context",
        ],
        "primary_context": primary,
        "exact_service_relationships": list(exact.service_relationships),
        "exact_module_relationships": _compact_module_relationships(
            exact.module_relationships
        ),
        "semantic_context": [asdict(fact) for fact in semantic],
        "source_and_test_locations": list(exact.source_and_test_locations),
        "affected_folder_specs": list(exact.affected_folder_specs),
        "interfaces_and_models": _references_for(primary, ("interface", "model")),
        "error_and_cleanup_context": _references_for(
            primary, ("error", "exception", "failure", "cleanup", "shutdown")
        ),
        "configuration_context": _references_for(
            primary, ("configuration", "environment", "setting")
        ),
        "resource_and_memory_context": _references_for(
            primary,
            ("memory", "resource", "cache", "queue", "task", "process", "device"),
        ),
        "secondary_context": secondary,
        "unresolved_questions": _unresolved_references(primary, secondary),
        "suggested_spec_scope": _suggested_scope(mode, exact),
    }
    _fit_budget(package, max_tokens)
    package["estimated_tokens"] = estimate_tokens(package)
    package["max_context_tokens"] = max_tokens
    return package


def render_markdown(package: dict[str, Any]) -> str:
    """Render a context package as reviewable Markdown."""

    lines = [
        "# Specification Brain Context",
        "",
        "## Request",
        "",
        str(package["request"]),
        "",
        "## Authority order",
        "",
    ]
    lines.extend(
        f"{index}. {value}"
        for index, value in enumerate(package["authority_order"], start=1)
    )
    lines.append("")
    _render_sections(lines, "Primary context", package["primary_context"])
    _render_json_section(
        lines,
        "Exact service relationships",
        package["exact_service_relationships"],
    )
    _render_json_section(
        lines,
        "Exact module relationships",
        package["exact_module_relationships"],
    )
    _render_json_section(lines, "Semantic context", package["semantic_context"])
    _render_json_section(
        lines,
        "Source and test locations",
        package["source_and_test_locations"],
    )
    _render_json_section(
        lines, "Affected folder specifications", package["affected_folder_specs"]
    )
    _render_sections(lines, "Secondary context", package["secondary_context"])
    _render_json_section(lines, "Unresolved questions", package["unresolved_questions"])
    _render_json_section(
        lines, "Suggested specification scope", package["suggested_spec_scope"]
    )
    lines.extend(
        [
            "## Budget",
            "",
            (
                f"Estimated tokens: {package['estimated_tokens']} / "
                f"{package['max_context_tokens']}"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def estimate_tokens(value: Any) -> int:
    """Return a conservative character-based context token estimate."""

    rendered = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return max(1, (len(rendered) + 2) // 3)


def _fit_budget(package: dict[str, Any], max_tokens: int) -> None:
    trim_stages = (
        ("secondary_context", 0),
        ("semantic_context", 2),
        ("primary_context", 6),
        ("source_and_test_locations", 12),
        ("affected_folder_specs", 12),
        ("primary_context", 3),
        ("semantic_context", 0),
        ("source_and_test_locations", 5),
        ("affected_folder_specs", 5),
        ("primary_context", 1),
        ("source_and_test_locations", 1),
        ("affected_folder_specs", 1),
        ("exact_service_relationships", 1),
        ("exact_module_relationships", 1),
    )
    for key, floor in trim_stages:
        values = package[key]
        while estimate_tokens(package) > max_tokens and len(values) > floor:
            values.pop()
            if key in {"primary_context", "secondary_context"}:
                _refresh_derived_references(package)
    if estimate_tokens(package) > max_tokens:
        raise ContextBudgetError(
            "the smallest useful evidence package exceeds the configured limit"
        )


def _refresh_derived_references(package: dict[str, Any]) -> None:
    primary = package["primary_context"]
    secondary = package["secondary_context"]
    package["interfaces_and_models"] = _references_for(primary, ("interface", "model"))
    package["error_and_cleanup_context"] = _references_for(
        primary, ("error", "exception", "failure", "cleanup", "shutdown")
    )
    package["configuration_context"] = _references_for(
        primary, ("configuration", "environment", "setting")
    )
    package["resource_and_memory_context"] = _references_for(
        primary,
        ("memory", "resource", "cache", "queue", "task", "process", "device"),
    )
    package["unresolved_questions"] = _unresolved_references(primary, secondary)


def _dedupe_records(
    records: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("stable_id") or _normalized_record_text(record))
        deduplicated.setdefault(key, record)
    return tuple(deduplicated.values())


def _dedupe_semantic(
    facts: Iterable[SemanticFact],
) -> tuple[SemanticFact, ...]:
    deduplicated: dict[str, SemanticFact] = {}
    for fact in facts:
        key = re.sub(r"\s+", " ", fact.fact).strip().lower()
        deduplicated.setdefault(key, fact)
    return tuple(deduplicated.values())


def _normalized_record_text(record: dict[str, Any]) -> str:
    value = str(record.get("body") or record.get("statement") or "")
    return re.sub(r"\s+", " ", value).strip().lower()


def _references_for(
    records: Iterable[dict[str, Any]], keywords: tuple[str, ...]
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for record in records:
        searchable = " ".join(
            (
                str(record.get("name", "")),
                " ".join(record.get("heading_path", [])),
                str(record.get("body", "")),
            )
        ).lower()
        if any(keyword in searchable for keyword in keywords):
            references.append(_record_reference(record))
    return references


def _unresolved_references(
    primary: Iterable[dict[str, Any]],
    secondary: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _references_for(
        (*tuple(primary), *tuple(secondary)),
        ("unresolved", "unknown", "open question", "requires confirmation"),
    )


def _record_reference(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "stable_id": record.get("stable_id"),
        "relative_path": record.get("relative_path"),
        "heading_path": record.get("heading_path", []),
    }


def _compact_module_relationships(
    relationships: Iterable[dict[str, Any]],
    per_direction_limit: int = 20,
) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for relationship in relationships:
        item: dict[str, Any] = {
            "owner": _graph_node_reference(relationship.get("owner")),
        }
        for direction in ("parents", "children", "dependencies", "consumers"):
            values = [
                _graph_node_reference(value)
                for value in relationship.get(direction, [])
                if value is not None
            ]
            item[direction] = values[:per_direction_limit]
            item[f"{direction}_total"] = len(values)
            item[f"{direction}_truncated"] = len(values) > per_direction_limit
        compact.append(item)
    return compact


def _graph_node_reference(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    node = dict(value)
    return {
        key: node.get(key)
        for key in ("stable_id", "name", "relative_path", "role")
        if node.get(key) is not None
    }


def _suggested_scope(mode: str, exact: ExactContext) -> dict[str, Any]:
    outputs = {
        "requirements": ["requirements.md"],
        "design": ["design.md"],
        "tasks": ["tasks.md"],
        "all": ["requirements.md", "design.md", "tasks.md"],
    }[mode]
    affected = [
        item["folder"].get("relative_path")
        for item in exact.affected_folder_specs
        if item.get("folder")
    ]
    return {
        "outputs": outputs,
        "affected_folders": list(dict.fromkeys(path for path in affected if path)),
        "requires_source_and_test_verification": True,
        "implementation_authorized": False,
    }


def _render_sections(
    lines: list[str], title: str, sections: list[dict[str, Any]]
) -> None:
    lines.extend([f"## {title}", ""])
    if not sections:
        lines.extend(["None found.", ""])
        return
    for section in sections:
        heading = section.get("name") or section.get("stable_id") or "Section"
        lines.extend(
            [
                f"### {heading}",
                "",
                f"Source: `{section.get('relative_path', 'unknown')}`",
                "",
                str(section.get("body", "")),
                "",
            ]
        )


def _render_json_section(lines: list[str], title: str, value: Any) -> None:
    lines.extend(
        [
            f"## {title}",
            "",
            "```json",
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False),
            "```",
            "",
        ]
    )
