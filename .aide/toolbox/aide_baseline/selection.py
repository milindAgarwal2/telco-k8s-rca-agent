"""Selectable Full and Extended workspace capabilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .profiles import detect_profiles
from .util import read_json

GROUPS = {
    "token-saver": (
        "Token Saver and metrics",
        "Response statistics, bounded log views, and local usage reports.",
    ),
    "jira-story": (
        "Jira story to specification",
        "Import a Jira story, refine EARS requirements, and start a spec.",
    ),
    "azure-observe": (
        "Azure observation",
        "Read Azure resource health and explain observed issues.",
    ),
    "azure-change": (
        "Azure changes",
        "Prepare and control reviewed Azure resource changes.",
    ),
    "kubernetes-observe": (
        "Kubernetes observation",
        "Inspect cluster resources and diagnose workload health.",
    ),
    "kubernetes-change": (
        "Kubernetes changes",
        "Prepare and control reviewed Kubernetes mutations.",
    ),
    "openwiki": (
        "OpenWiki",
        "Create and maintain the repository wiki with its MCP lifecycle.",
    ),
    "knowledge-graph": (
        "Knowledge graph assistant",
        "Curate and explain source-linked knowledge across graph layers.",
    ),
    "loop-engineering": (
        "Loop engineering",
        "Design and evaluate bounded development loops.",
    ),
}

GROUP_MEMBERS = {
    "token-saver": {
        "mcp:aide-token-saver",
        "hook:aide-token-saver",
        "skill:aide-token",
        "skill:aide-kiro-metrics",
    },
    "jira-story": {
        "mcp:jira",
        "hook:aide-story-lifecycle",
        "skill:aide-jira-story-import",
        "skill:aide-ears-story-refinement",
        "agent:aide-spec-planner",
    },
    "azure-observe": {
        "mcp:aide-azure-mcp",
        "hook:aide-azure-observability",
        "skill:aide-azure-observability",
        "agent:aide-azure-observer",
    },
    "azure-change": {
        "mcp:aide-azure-change-mcp",
        "hook:aide-azure-change-control",
        "skill:aide-azure-change-control",
        "agent:aide-azure-operator",
    },
    "kubernetes-observe": {
        "mcp:aide-kubernetes-mcp",
        "hook:aide-kubernetes-observability",
        "skill:aide-kubernetes-operations",
        "agent:aide-kubernetes-observer",
    },
    "kubernetes-change": {
        "mcp:aide-kubernetes-change-mcp",
        "hook:aide-kubernetes-change-control",
        "skill:aide-kubernetes-change-control",
        "agent:aide-kubernetes-operator",
    },
    "openwiki": {
        "mcp:openwiki",
        "skill:openwiki",
        "agent:aide-openwiki",
    },
    "knowledge-graph": {
        "skill:aide-knowledge-graph",
        "agent:aide-knowledge-graph",
    },
    "loop-engineering": {
        "skill:aide-loop-engineering",
        "agent:aide-loop-engineer",
    },
}

REQUIRES = {
    "hook:aide-token-saver": ["mcp:aide-token-saver"],
    "skill:aide-token": ["mcp:aide-token-saver"],
    "skill:aide-kiro-metrics": ["mcp:aide-token-saver"],
    "skill:aide-jira-story-import": ["mcp:jira"],
    "hook:aide-story-lifecycle": [
        "skill:spec-brain",
        "skill:aide-spec-authoring",
    ],
    "agent:aide-azure-observer": ["skill:aide-azure-observability"],
    "hook:aide-azure-observability": ["mcp:aide-azure-mcp"],
    "agent:aide-azure-operator": ["skill:aide-azure-change-control"],
    "skill:aide-azure-change-control": ["mcp:aide-azure-change-mcp"],
    "hook:aide-azure-change-control": ["mcp:aide-azure-change-mcp"],
    "agent:aide-kubernetes-observer": ["skill:aide-kubernetes-operations"],
    "hook:aide-kubernetes-observability": ["mcp:aide-kubernetes-mcp"],
    "agent:aide-kubernetes-operator": ["skill:aide-kubernetes-change-control"],
    "skill:aide-kubernetes-change-control": ["mcp:aide-kubernetes-change-mcp"],
    "hook:aide-kubernetes-change-control": ["mcp:aide-kubernetes-change-mcp"],
    "agent:aide-openwiki": ["skill:openwiki", "mcp:openwiki"],
    "agent:aide-knowledge-graph": ["skill:aide-knowledge-graph"],
    "agent:aide-loop-engineer": ["skill:aide-loop-engineering"],
}

MCP_DESCRIPTIONS = {
    "aide-architecture-mcp": (
        "Read repository architecture contracts and relationships."
    ),
    "aide-azure-change-mcp": "Stage policy-checked Azure resource changes.",
    "aide-azure-mcp": "Inspect Azure resources through the signed-in CLI.",
    "aide-knowledge-mcp": "Search the local source-linked knowledge base.",
    "aide-kubernetes-change-mcp": "Stage policy-checked Kubernetes changes.",
    "aide-kubernetes-mcp": "Inspect Kubernetes resources and workload health.",
    "aide-spec-mcp": "Read and validate repository specifications.",
    "aide-token-saver": "Report local response metrics and bounded log savings.",
    "devportal": "Access the configured internal developer portal.",
    "eds-mcp": "Read the configured Ericsson design system service.",
    "filesystem": "Access permitted local workspace files.",
    "git": "Inspect repository history and changes.",
    "glean": "Search the configured enterprise knowledge service.",
    "graphiti": "Query temporal knowledge and contextual memory.",
    "jira": "Read Jira stories and project details.",
    "lean-ctx": "Read compact local context; enabled by Extended.",
    "memory": "Store and retrieve local MCP memory.",
    "neo4j": "Inspect the shared Neo4j knowledge graph.",
    "openwiki": "Run the OpenWiki page-job lifecycle.",
    "postgres": "Inspect a configured PostgreSQL database.",
    "postgresql": "Access an optional PostgreSQL MCP server.",
    "scas": "Run the packaged governance analysis service.",
}


def _skill_description(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()[:20]
    for line in lines:
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return f"Guidance for {path.parent.name.replace('-', ' ')}."


def _group_for(item_id: str) -> str | None:
    return next(
        (name for name, members in GROUP_MEMBERS.items() if item_id in members), None
    )


def selection_catalog(source: Path, target: Path, flavor: str) -> dict[str, Any]:
    """Describe installable items and their required relationships."""

    if flavor not in {"full", "extended"}:
        raise ConfigurationError("Component selection requires Full or Extended.")
    items: list[dict[str, Any]] = []

    def add(
        kind: str, name: str, description: str, requires: list[str] | None = None
    ) -> None:
        item_id = f"{kind}:{name}"
        items.append(
            {
                "id": item_id,
                "kind": kind,
                "name": name,
                "description": description.strip(),
                "group": _group_for(item_id),
                "requires": sorted(
                    set(REQUIRES.get(item_id, [])) | set(requires or [])
                ),
            }
        )

    for area in ("shared", "optional"):
        for path in sorted((source / "catalog" / "agents" / area).glob("*.json")):
            data = read_json(path)
            add(
                "agent",
                path.stem,
                data.get("description", "Repository assistant."),
                [f"skill:{name}" for name in data.get("skills", [])],
            )
    skill_roots = [
        source / "catalog" / "skills" / "shared",
        source / "catalog" / "skills" / "workflows",
        source / "catalog" / "flavors" / "full" / "skills",
    ]
    detected = detect_profiles(target)
    for profile in detected["profiles"]:
        if profile != "mixed":
            skill_roots.append(source / "catalog" / "skills" / "profiles" / profile)
    seen_skills: set[str] = set()
    for root in skill_roots:
        for path in sorted(root.glob("*/SKILL.md")):
            if path.parent.name not in seen_skills:
                seen_skills.add(path.parent.name)
                add("skill", path.parent.name, _skill_description(path))
    full = source / "catalog" / "flavors" / "full"
    for path in sorted((full / "hooks").glob("*.json")):
        data = read_json(path)
        hooks = data.get("hooks", [])
        description = (
            hooks[0].get("description", "Kiro workflow event hook.")
            if hooks
            else "Kiro workflow event hook."
        )
        add("hook", path.stem, description)
    for path in sorted((full / "mcp").glob("*.json")):
        data = read_json(path)
        name = next(iter(data["mcpServers"]))
        add(
            "mcp",
            name,
            MCP_DESCRIPTIONS.get(name, f"Connect the {name} workspace MCP server."),
        )
    ids = {item["id"] for item in items}
    for item in items:
        missing = set(item["requires"]) - ids
        if missing:
            raise ConfigurationError(
                f"Missing packaged prerequisites for {item['id']}: {sorted(missing)}"
            )
    project_path = target / ".aide" / "project.json"
    project = read_json(project_path) if project_path.exists() else {}
    excluded = set(project.get("excluded_items", []))
    changed = True
    while changed:
        changed = False
        for item in items:
            if item["id"] not in excluded and set(item["requires"]) & excluded:
                excluded.add(item["id"])
                changed = True
    for item in items:
        item["selected"] = item["id"] not in excluded
    groups = [
        {"id": key, "name": name, "description": description}
        for key, (name, description) in GROUPS.items()
        if any(item["group"] == key for item in items)
    ]
    return {"schema_version": 1, "flavor": flavor, "groups": groups, "items": items}


def resolve_selection(
    catalog: dict[str, Any], selected: list[str] | None
) -> tuple[set[str], list[str]]:
    """Validate an explicit selection or retain existing exclusions."""

    items = {item["id"]: item for item in catalog["items"]}
    if selected is None:
        chosen = {item_id for item_id, item in items.items() if item["selected"]}
    else:
        if len(selected) != len(set(selected)):
            raise ConfigurationError("Component selection has duplicate IDs.")
        chosen = set(selected)
    unknown = chosen - items.keys()
    if unknown:
        raise ConfigurationError(
            "Unknown selected components: " + ", ".join(sorted(unknown))
        )
    for item_id in sorted(chosen):
        missing = set(items[item_id]["requires"]) - chosen
        if missing:
            raise ConfigurationError(
                f"{item_id} requires selected components: {', '.join(sorted(missing))}"
            )
    return chosen, sorted(items.keys() - chosen)


def read_selection_file(path: Path) -> list[str]:
    """Read the reviewer's selection without interpreting executable input."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid component selection file: {exc}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("selected"), list)
    ):
        raise ConfigurationError(
            "Component selection file needs schema_version 1 and selected IDs."
        )
    if not all(isinstance(item, str) for item in value["selected"]):
        raise ConfigurationError("Selected component IDs must be strings.")
    return value["selected"]
