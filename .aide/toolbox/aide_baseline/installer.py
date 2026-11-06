"""AIDE overlay installer, updater, bootstrapper, remover, and resetter."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, ConflictError, SafetyError
from .hooks import HOOKS, render_cli2_embedded, render_current
from .integrations import load_catalog, render_mcp_entry
from .lean_ctx import VERSION as LEAN_CTX_VERSION
from .lean_ctx import current_asset, install_needed, prepare_binary, verify_binary
from .profiles import detect_profiles
from .selection import resolve_selection, selection_catalog
from .util import (
    FileTransaction,
    canonical_json,
    find_git_root,
    is_reparse_point,
    read_json,
    safe_join,
    sha256_bytes,
    sha256_file,
    sha256_value,
    utc_now,
)
from .validation import validate_contract

IGNORE_START = "# AIDE-BASELINE:START"
IGNORE_END = "# AIDE-BASELINE:END"
IGNORE_BODY = """# AIDE-BASELINE:START
.aide/local/
.framework-governance/
.aide/**/__pycache__/
.aide/**/*.py[cod]
.kiro/**/__pycache__/
.kiro/**/*.py[cod]
# AIDE-BASELINE:END
"""

GENERATED_CATALOG_DIRECTORIES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
    "__pycache__",
}
GENERATED_CATALOG_SUFFIXES = {".pyc", ".pyo"}

TOKEN_SAVER_AGENT_PROMPT = """

# AIDE response statistics

For every final response, call 'aide_token_stats' exactly once immediately before
responding when the tool is available. End with one compact line in this format:
'AIDE stats · tools N · observed payload ≈N tokens · log-view delta ≈N · provider
usage unavailable'. Use the returned values, label estimates honestly, and never
invent provider usage or savings. If the tool is unavailable, finish normally after
one attempt.

When the user asks for a Token Saver report, call 'aide_token_report' once. Lead with
its easy-language headline, show the technique table, and render both supplied Mermaid
charts, using their text fallbacks when Mermaid is unsupported. Call only positive
measured log representation deltas savings. Do not invent a provider-wide token or
monetary saving.
"""


@dataclass
class Plan:
    """One inspectable installer plan."""

    operation: str
    target: str
    flavor: str = "minimal"
    actions: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    applied: bool = False

    @property
    def changed(self) -> int:
        return sum(
            item["action"] in {"ADD", "UPDATE", "REMOVE", "MERGE", "RELINQUISH"}
            for item in self.actions
        )

    def as_dict(self) -> dict[str, Any]:
        if self.conflicts:
            status = "CONFLICT"
        elif self.applied:
            status = "APPLIED"
        else:
            status = "READY"
        return {
            "operation": self.operation,
            "target": self.target,
            "flavor": self.flavor,
            "actions": self.actions,
            "conflicts": self.conflicts,
            "warnings": self.warnings,
            "changed": self.changed,
            "status": status,
        }


def baseline_version(source_root: Path) -> str:
    return (source_root / "VERSION").read_text(encoding="utf-8").strip()


def validate_source(source_root: Path) -> dict[str, Any]:
    """Validate the distribution manifest and all declared source files."""

    manifest = read_json(source_root / "manifest.json")
    if manifest.get("schema_version") != 1:
        raise ConfigurationError("Unsupported baseline manifest schema.")
    if manifest.get("version") != baseline_version(source_root):
        raise ConfigurationError("VERSION and manifest version disagree.")
    missing = []
    for relative in manifest.get("required_paths", []):
        path = source_root / relative
        if not path.exists():
            missing.append(relative)
    if missing:
        raise ConfigurationError("Distribution is incomplete: " + ", ".join(missing))
    for path in (source_root / "profiles").glob("*.json"):
        profile = read_json(path)
        if profile.get("schema_version") != 1 or profile.get("name") != path.stem:
            raise ConfigurationError(f"Invalid profile descriptor: {path}")
    for path in (source_root / "mcp" / "descriptors").glob("*.json"):
        descriptor = read_json(path)
        required = {
            "schema_version",
            "name",
            "purpose",
            "upstream",
            "version",
            "license",
            "integrity",
            "runtime",
            "transport",
            "supported_os",
            "capabilities",
            "setup_steps",
            "health_check",
            "secret_refs",
            "kiro_template",
            "permissions",
            "removal_owner",
        }
        if descriptor.get("schema_version") != 1 or required - set(descriptor):
            raise ConfigurationError(f"Invalid integration descriptor: {path}")
        if "${env:" in json.dumps(descriptor.get("kiro_template", {})):
            raise ConfigurationError(
                f"Obsolete Kiro environment reference syntax in: {path}"
            )

    full_root = source_root / "catalog" / "flavors" / "full"
    full = read_json(full_root / "flavor.json")
    if (
        full.get("schema_version") != 1
        or full.get("name") != "full"
        or "all" not in full.get("aliases", [])
    ):
        raise ConfigurationError("Invalid full-flavor descriptor.")
    extended = read_json(
        source_root / "catalog" / "flavors" / "extended" / "flavor.json"
    )
    if extended != {
        "schema_version": 1,
        "name": "extended",
        "extends": "full",
        "lean_ctx_version": LEAN_CTX_VERSION,
    }:
        raise ConfigurationError("Invalid extended-flavor descriptor.")

    inventories: dict[str, set[str]] = {
        "agents": {
            read_json(path).get("name")
            for directory in ("shared", "optional")
            for path in (source_root / "catalog" / "agents" / directory).glob("*.json")
        },
        "skills": {
            path.parent.name for path in (full_root / "skills").glob("*/SKILL.md")
        },
        "hooks": {path.stem for path in (full_root / "hooks").glob("*.json")},
        "workspace_mcp_servers": set(),
    }
    for path in (full_root / "mcp").glob("*.json"):
        value = read_json(path)
        servers = value.get("mcpServers")
        if not isinstance(servers, dict) or len(servers) != 1:
            raise ConfigurationError(f"Invalid full-flavor MCP template: {path}")
        if "${env:" in json.dumps(servers):
            raise ConfigurationError(
                f"Obsolete Kiro environment reference syntax in: {path}"
            )
        inventories["workspace_mcp_servers"].update(servers)

    for key, actual in inventories.items():
        declared = full.get(key)
        if not isinstance(declared, list) or len(declared) != len(set(declared)):
            raise ConfigurationError(f"Invalid full-flavor {key} inventory.")
        if set(declared) != actual:
            raise ConfigurationError(
                f"Full-flavor {key} inventory does not match packaged files."
            )
    return manifest


def validate_project(project: dict[str, Any], source_root: Path | None = None) -> None:
    """Validate portable installed project configuration."""

    required = {
        "schema_version",
        "baseline_version",
        "profiles",
        "components",
        "integrations",
        "kiro_target",
        "validation",
        "module_mappings",
    }
    if project.get("schema_version") != 1 or required - set(project):
        raise ConfigurationError(
            "Installed .aide/project.json is incomplete or unsupported."
        )
    if project["kiro_target"] not in {"current", "cli2"}:
        raise ConfigurationError("Unsupported Kiro target in project configuration.")
    if project.get("flavor", "minimal") not in {"minimal", "full", "extended"}:
        raise ConfigurationError("Unsupported AIDE installation flavor.")
    excluded = project.get("excluded_items", [])
    if not isinstance(excluded, list) or any(
        not isinstance(item, str) for item in excluded
    ):
        raise ConfigurationError(
            "Invalid excluded component IDs in project configuration."
        )
    available_profiles = (
        {path.stem for path in (source_root / "profiles").glob("*.json")}
        if source_root
        else {
            "python",
            "java",
            "go",
            "kotlin",
            "php",
            "rust",
            "angular",
            "bash",
            "ansible",
            "postman",
            "kubernetes",
            "gitops",
            "fluxcd",
            "mixed",
        }
    )
    unknown_profiles = set(project["profiles"]) - available_profiles
    if unknown_profiles:
        raise ConfigurationError(
            "Unknown project profiles: " + ", ".join(sorted(unknown_profiles))
        )
    for mapping in project["module_mappings"]:
        relative = mapping.get("path")
        if relative not in {"", "."}:
            from .util import normalize_relative

            normalize_relative(relative)
    for contract in project["validation"]:
        validate_contract(contract)


def detect_kiro_target(requested: str) -> tuple[str, str]:
    """Select a tested renderer without changing Kiro configuration."""

    if requested in {"current", "cli2"}:
        return requested, "explicit"
    executable = shutil.which("kiro-cli") or shutil.which("kiro-cli-chat")
    if not executable:
        return (
            "current",
            "Kiro CLI not found; current format selected but unverified locally",
        )
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "current", "Kiro version unreadable; current format selected"
    match = re.search(r"(\d+)\.(\d+)", completed.stdout + completed.stderr)
    if match and int(match.group(1)) == 2:
        return "cli2", (completed.stdout or completed.stderr).strip()
    return "current", (completed.stdout or completed.stderr).strip()


def _catalog_files(
    source_root: Path,
    profiles: list[str],
    components: list[str],
    flavor: str,
    selected_items: set[str] | None = None,
) -> dict[str, bytes]:
    """Build portable overlay content from reusable catalogue files."""

    desired: dict[str, bytes] = {}
    mappings: list[tuple[str, str]] = []
    if "shared" in components:
        mappings.extend(
            [
                ("catalog/steering", ".kiro/steering"),
                ("catalog/assets", "assets"),
                ("catalog/loops", "loops"),
                ("catalog/skills/shared", ".kiro/skills"),
                ("catalog/prompts", "prompt"),
                ("catalog/kiro-prompts", ".kiro/prompts"),
                ("templates", ".aide/templates"),
                ("mcp/descriptors", ".aide/integrations/descriptors"),
            ]
        )
    if "workflows" in components:
        mappings.extend(
            [
                ("catalog/skills/workflows", ".kiro/skills"),
                ("workflows/definitions", ".aide/workflows/definitions"),
                ("workflows/templates", ".aide/workflows/templates"),
            ]
        )
    if "profiles" in components:
        for profile in profiles:
            source = source_root / "catalog" / "skills" / "profiles" / profile
            if source.exists():
                mappings.append((f"catalog/skills/profiles/{profile}", ".kiro/skills"))
    if flavor in {"full", "extended"}:
        mappings.extend(
            [
                ("catalog/flavors/full/skills", ".kiro/skills"),
                ("catalog/flavors/full/steering", ".kiro/steering"),
                ("catalog/flavors/full/dashboard", ".aide/full/dashboard"),
                ("catalog/flavors/full/runtimes/hook", ".aide/full/hook"),
                (
                    "catalog/flavors/full/runtimes/aide-knowledge-mcp",
                    ".aide/full/mcp-servers/aide-knowledge-mcp",
                ),
                (
                    "catalog/flavors/full/runtimes/aide-architecture-mcp",
                    ".aide/full/mcp-servers/aide-architecture-mcp",
                ),
                (
                    "catalog/flavors/full/runtimes/aide-spec-mcp",
                    ".aide/full/mcp-servers/aide-spec-mcp",
                ),
                (
                    "catalog/flavors/full/runtimes/aide-azure-mcp",
                    ".aide/full/mcp-servers/aide-azure-mcp",
                ),
                (
                    "catalog/flavors/full/runtimes/aide-azure-change-mcp",
                    ".aide/full/mcp-servers/aide-azure-change-mcp",
                ),
                (
                    "catalog/flavors/full/runtimes/aide-kubernetes-mcp",
                    ".aide/full/mcp-servers/aide-kubernetes-mcp",
                ),
                (
                    "catalog/flavors/full/runtimes/aide-kubernetes-change-mcp",
                    ".aide/full/mcp-servers/aide-kubernetes-change-mcp",
                ),
                (
                    "catalog/flavors/full/runtimes/aide-token-saver",
                    ".aide/full/mcp-servers/aide-token-saver",
                ),
                (
                    "catalog/flavors/full/runtimes/spec-brain",
                    ".aide/full/spec-brain",
                ),
                ("catalog/flavors/full/runtimes/scas", ".aide/full/scas"),
            ]
        )
    for source_relative, destination_relative in mappings:
        source = source_root / source_relative
        if not source.exists():
            continue
        for path in source.rglob("*"):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(source).as_posix()
                if _is_generated_catalog_artifact(Path(relative)):
                    continue
                if "/runtimes/" in f"/{source_relative}/" and not (
                    relative
                    in {
                        ".gitignore",
                        "README.md",
                        "policy.json",
                        "pyproject.toml",
                        "uv.lock",
                    }
                    or (relative.startswith("src/") and path.suffix == ".py")
                    or (
                        relative.startswith("tools/")
                        and path.suffix in {".py", ".md", ".txt"}
                    )
                    or (
                        source_relative == "catalog/flavors/full/runtimes/scas"
                        and (
                            (
                                relative.startswith("knowledge-base/")
                                and path.suffix == ".md"
                            )
                            or (
                                relative.startswith("config/")
                                and path.suffix == ".json"
                            )
                        )
                    )
                ):
                    continue
                desired[f"{destination_relative}/{relative}"] = path.read_bytes()
    for path in (source_root / "toolbox").rglob("*"):
        if path.is_file() and not path.is_symlink():
            relative = path.relative_to(source_root / "toolbox")
            if _is_generated_catalog_artifact(relative):
                continue
            desired[f".aide/toolbox/{relative.as_posix()}"] = path.read_bytes()
    if selected_items is not None:
        for relative in list(desired):
            skill = re.match(r"^\.kiro/skills/([^/]+)/", relative)
            if skill and f"skill:{skill.group(1)}" not in selected_items:
                del desired[relative]
                continue
            runtime = re.match(r"^\.aide/full/mcp-servers/([^/]+)/", relative)
            if runtime and f"mcp:{runtime.group(1)}" not in selected_items:
                del desired[relative]
                continue
            if (
                relative.startswith(".aide/full/scas/")
                and "mcp:scas" not in selected_items
            ):
                del desired[relative]
                continue
            if relative.startswith(".aide/full/dashboard/") and (
                "mcp:aide-token-saver" not in selected_items
            ):
                del desired[relative]
                continue
            if relative.startswith(".aide/full/spec-brain/") and not (
                {"skill:spec-brain", "mcp:aide-spec-mcp"} & selected_items
            ):
                del desired[relative]
                continue
            if relative.startswith(".aide/full/hook/") and not any(
                item.startswith("hook:") for item in selected_items
            ):
                del desired[relative]
    return desired


def _is_generated_catalog_artifact(relative: Path) -> bool:
    """Return whether a catalog path is generated local Python state."""

    return bool(
        GENERATED_CATALOG_DIRECTORIES.intersection(relative.parts)
        or relative.suffix.lower() in GENERATED_CATALOG_SUFFIXES
    )


def _render_agents(
    source_root: Path,
    kiro_target: str,
    include_optional: bool,
    flavor: str,
    selected_items: set[str] | None = None,
) -> dict[str, bytes]:
    rendered: dict[str, bytes] = {}
    paths = sorted((source_root / "catalog" / "agents" / "shared").glob("*.json"))
    if include_optional:
        paths += sorted(
            (source_root / "catalog" / "agents" / "optional").glob("*.json")
        )
    for path in paths:
        if selected_items is not None and f"agent:{path.stem}" not in selected_items:
            continue
        definition = read_json(path)
        token_saver = flavor in {"full", "extended"} and (
            selected_items is None or "mcp:aide-token-saver" in selected_items
        )
        if token_saver:
            definition["prompt"] = (
                definition.get("prompt", "").rstrip() + TOKEN_SAVER_AGENT_PROMPT
            )
        skill_resources = (
            ["skill://.kiro/skills/**/SKILL.md"]
            if flavor in {"full", "extended"}
            else [
                f"skill://.kiro/skills/{name}/SKILL.md"
                for name in definition.get("skills", [])
            ]
        )
        definition["resources"] = [
            *skill_resources,
            "file://.kiro/steering/bos-aide-response-style.md",
            "file://.kiro/steering/aide-token-defaults.md",
        ]
        if flavor in {"full", "extended"}:
            definition["resources"].append("file://.kiro/steering/aide-ponytail.md")
        definition.pop("skills", None)
        if kiro_target == "cli2":
            definition["tools"] = definition.get(
                "legacy_tools", ["fs_read", "grep", "glob"]
            )
            if token_saver and "@aide-token-saver" not in definition["tools"]:
                definition["tools"].append("@aide-token-saver")
            if (
                flavor == "extended"
                and (selected_items is None or "mcp:lean-ctx" in selected_items)
                and "@lean-ctx" not in definition["tools"]
            ):
                definition["tools"].append("@lean-ctx")
            definition.pop("legacy_tools", None)
            definition.pop("permissions", None)
            definition.pop("includeMcpJson", None)
            definition["hooks"] = render_cli2_embedded(
                include_token_saver=token_saver
                and (
                    selected_items is None or "hook:aide-token-saver" in selected_items
                ),
                include_names=None
                if selected_items is None
                else {item[5:] for item in selected_items if item.startswith("hook:")},
            )
        else:
            if token_saver and "@aide-token-saver" not in definition["tools"]:
                definition["tools"].append("@aide-token-saver")
            if (
                flavor == "extended"
                and (selected_items is None or "mcp:lean-ctx" in selected_items)
                and "@lean-ctx" not in definition["tools"]
            ):
                definition["tools"].append("@lean-ctx")
            definition.pop("legacy_tools", None)
        if selected_items is not None:
            definition["tools"] = [
                tool
                for tool in definition["tools"]
                if not tool.startswith("@") or f"mcp:{tool[1:]}" in selected_items
            ]
        rendered[f".kiro/agents/{path.name}"] = canonical_json(definition)
    return rendered


def _render_hooks(
    source_root: Path, flavor: str, selected_items: set[str] | None = None
) -> dict[str, bytes]:
    if flavor in {"full", "extended"}:
        return {
            f".kiro/hooks/{path.name}": path.read_bytes()
            for path in sorted(
                (source_root / "catalog" / "flavors" / "full" / "hooks").glob("*.json")
            )
            if selected_items is None or f"hook:{path.stem}" in selected_items
        }
    return {f".kiro/hooks/{name}.json": render_current(name) for name in HOOKS}


def _load_full_mcp(source_root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    catalog = source_root / "catalog" / "flavors" / "full" / "mcp"
    for path in sorted(catalog.glob("*.json")):
        value = read_json(path)
        servers = value.get("mcpServers")
        if not isinstance(servers, dict) or len(servers) != 1:
            raise ConfigurationError(
                f"Full-flavor MCP template must define one server: {path}"
            )
        name, entry = next(iter(servers.items()))
        if name in entries or not isinstance(entry, dict):
            raise ConfigurationError(f"Invalid full-flavor MCP template: {path}")
        if os.name != "nt" and entry.get("command") == "cmd":
            args = entry.get("args", [])
            if args[:2] == ["/c", "npx"]:
                entry["command"] = "npx"
                entry["args"] = args[2:]
        entries[name] = entry
    return entries


def _existing_gitignore(root: Path) -> tuple[bytes | None, bytes]:
    path = root / ".gitignore"
    if path.exists() and is_reparse_point(path):
        raise SafetyError(f"Refusing linked ignore file: {path}")
    original = path.read_bytes() if path.exists() else None
    text = original.decode("utf-8") if original else ""
    if (IGNORE_START in text) != (IGNORE_END in text):
        raise ConflictError(
            "Existing .gitignore contains an incomplete AIDE marked block."
        )
    if IGNORE_START in text and IGNORE_END in text:
        start = text.index(IGNORE_START)
        end = text.index(IGNORE_END, start) + len(IGNORE_END)
        suffix = text[end:]
        if suffix.startswith("\r\n"):
            suffix = suffix[2:]
        elif suffix.startswith("\n"):
            suffix = suffix[1:]
        updated = text[:start] + IGNORE_BODY + suffix
        return original, updated.encode("utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    return original, (text + IGNORE_BODY).encode("utf-8")


def _merge_mcp(
    root: Path,
    source_root: Path,
    integrations: list[str],
    flavor: str,
    previously_owned: dict[str, str],
    previously_preserved: set[str],
    selected_items: set[str] | None = None,
) -> tuple[bytes | None, bytes | None, list[str], list[str], list[str]]:
    if not integrations and flavor not in {"full", "extended"} and not previously_owned:
        return None, None, [], sorted(previously_preserved), []
    path = root / ".kiro" / "settings" / "mcp.json"
    if path.exists() and is_reparse_point(path):
        raise SafetyError(f"Refusing linked MCP settings file: {path}")
    original = path.read_bytes() if path.exists() else None
    if original:
        try:
            value = json.loads(original)
        except json.JSONDecodeError as exc:
            raise ConflictError(
                f"Existing Kiro MCP JSON is invalid: {path}: {exc}"
            ) from exc
    else:
        value = {"mcpServers": {}}
    servers = value.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConflictError("Existing mcpServers value must be a JSON object.")
    catalog = load_catalog(source_root)
    candidates = _load_full_mcp(source_root) if flavor in {"full", "extended"} else {}
    if selected_items is not None:
        candidates = {
            name: entry
            for name, entry in candidates.items()
            if f"mcp:{name}" in selected_items
        }
    if flavor == "extended" and "lean-ctx" in candidates:
        lean_ctx = candidates["lean-ctx"].copy()
        lean_ctx["command"] = "uv"
        lean_ctx["args"] = [
            "run",
            "--quiet",
            "--offline",
            "--no-project",
            ".aide/toolbox/aide_baseline/lean_ctx_proxy.py",
            current_asset().mcp_command,
        ]
        lean_ctx["env"] = {"LEAN_CTX_NO_UPDATE_CHECK": "1"}
        lean_ctx["disabled"] = False
        candidates["lean-ctx"] = lean_ctx
    for name in integrations:
        if name not in catalog:
            raise ConfigurationError(f"Unknown integration: {name}")
        candidates.setdefault(name, render_mcp_entry(catalog[name]))
    owned = []
    preserved = []
    removed = []
    for name, candidate in candidates.items():
        if name in previously_preserved:
            preserved.append(name)
            continue
        if name not in servers:
            if name in previously_owned:
                preserved.append(name)
                continue
            servers[name] = candidate
            owned.append(name)
            continue
        if name in previously_owned:
            if servers[name] == candidate:
                owned.append(name)
                continue
            if sha256_value(servers[name]) != previously_owned[name]:
                preserved.append(name)
                continue
            servers[name] = candidate
            owned.append(name)
            continue
        preserved.append(name)
    for name, expected_hash in previously_owned.items():
        if name in candidates:
            continue
        if name not in servers:
            preserved.append(name)
            continue
        if sha256_value(servers[name]) != expected_hash:
            preserved.append(name)
            continue
        servers.pop(name)
        removed.append(name)
    return original, canonical_json(value), owned, preserved, removed


def desired_overlay(
    root: Path,
    source_root: Path,
    profiles: list[str],
    integrations: list[str],
    kiro_target: str,
    components: list[str],
    flavor: str,
    previously_owned_files: set[str] | None = None,
    create_knowledge_base: bool = True,
    selected_items: set[str] | None = None,
    excluded_items: list[str] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Build all managed files without mutating the target."""

    desired = _catalog_files(source_root, profiles, components, flavor, selected_items)
    if "shared" in components:
        owned_files = previously_owned_files or set()
        placeholder = "knowledge-base/.gitkeep"
        knowledge_base = safe_join(root, "knowledge-base")
        if placeholder in owned_files or (
            create_knowledge_base and not knowledge_base.exists()
        ):
            desired[placeholder] = (
                source_root / "catalog" / "knowledge-base" / ".gitkeep"
            ).read_bytes()
        if flavor in {"full", "extended"}:
            for relative, source in (
                (".openwikiignore", "catalog/openwiki/.openwikiignore"),
                (
                    "openwiki/INSTRUCTIONS.md",
                    "catalog/openwiki/INSTRUCTIONS.md",
                ),
            ):
                target = safe_join(root, relative)
                if not target.exists() or relative in owned_files:
                    desired[relative] = (source_root / source).read_bytes()
        desired.update(
            _render_agents(
                source_root,
                kiro_target,
                "optional-agents" in components,
                flavor,
                selected_items,
            )
        )
        desired.update(_render_hooks(source_root, flavor, selected_items))
    project = {
        "schema_version": 1,
        "baseline_version": baseline_version(source_root),
        "flavor": flavor,
        "profiles": profiles,
        "integrations": integrations,
        "components": components,
        "excluded_items": excluded_items or [],
        "kiro_target": kiro_target,
        "validation": [],
        "module_mappings": detect_profiles(root)["modules"],
    }
    desired[".aide/project.json"] = canonical_json(project)
    desired[".aide/README.md"] = (
        b"# Installed AIDE overlay\n\nCommitted configuration is portable. "
        b"Local runs and approval receipts live under ignored `.aide/local/`.\n"
    )
    return desired, project


def _load_ownership(root: Path) -> dict[str, Any]:
    path = safe_join(root, ".aide/managed-files.json")
    return (
        read_json(path)
        if path.exists()
        else {"schema_version": 1, "files": {}, "settings": {}}
    )


def _customizable_workspace_scope(relative: str) -> str | None:
    """Return the user-owned scope for a customizable workspace artifact."""

    if relative.startswith(".aide/"):
        return None
    parts = relative.split("/")
    if len(parts) >= 3 and parts[:2] in ([".kiro", "skills"], [".agents", "skills"]):
        return "/".join(parts[:3])
    return relative


def install(
    target: Path,
    source_root: Path,
    *,
    profiles: list[str] | None = None,
    integrations: list[str] | None = None,
    components: list[str] | None = None,
    kiro_target: str = "auto",
    flavor: str = "minimal",
    apply: bool = False,
    operation: str = "install",
    create_knowledge_base: bool = True,
    selected_items: list[str] | None = None,
) -> Plan:
    """Plan or apply a non-destructive install/update."""

    validate_source(source_root)
    root = find_git_root(target)
    if is_reparse_point(root):
        raise SafetyError(f"Refusing reparse-point target: {root}")
    normalized_flavor = "full" if flavor == "all" else flavor
    if normalized_flavor not in {"minimal", "full", "extended"}:
        raise ConfigurationError("Flavor must be minimal, full, extended, or all.")
    detected = detect_profiles(root)
    selected_profiles = sorted(
        set(profiles or [p for p in detected["profiles"] if p != "mixed"])
    )
    selected_integrations = sorted(set(integrations or []))
    selected_components = sorted(set(components or ["shared", "workflows", "profiles"]))
    if normalized_flavor in {"full", "extended"}:
        selected_components = sorted(set(selected_components) | {"optional-agents"})
    supported_components = {"shared", "workflows", "profiles", "optional-agents"}
    unknown_components = set(selected_components) - supported_components
    if unknown_components:
        raise ConfigurationError(
            "Unknown components: " + ", ".join(sorted(unknown_components))
        )
    chosen_items: set[str] | None = None
    excluded_items: list[str] = []
    if normalized_flavor in {"full", "extended"}:
        catalog = selection_catalog(source_root, root, normalized_flavor)
        chosen_items, excluded_items = resolve_selection(catalog, selected_items)
    elif selected_items is not None:
        raise ConfigurationError("Component selection requires Full or Extended.")
    available_profiles = {
        path.stem for path in (source_root / "profiles").glob("*.json")
    }
    unknown_profiles = set(selected_profiles) - available_profiles
    if unknown_profiles:
        raise ConfigurationError(
            "Unknown profiles: " + ", ".join(sorted(unknown_profiles))
        )
    target_format, target_note = detect_kiro_target(kiro_target)
    ownership = _load_ownership(root)
    old_files = ownership.get("files", {})
    preserved_ownership = ownership.get("preserved", {})
    if not isinstance(preserved_ownership, dict):
        preserved_ownership = {}
    previous_workspace_scopes = {
        item
        for item in preserved_ownership.get("workspace_scopes", [])
        if isinstance(item, str)
    }
    previous_mcp_preserved = {
        item
        for item in preserved_ownership.get("mcp_entries", [])
        if isinstance(item, str)
    }
    desired, project = desired_overlay(
        root,
        source_root,
        selected_profiles,
        selected_integrations,
        target_format,
        selected_components,
        normalized_flavor,
        set(old_files),
        create_knowledge_base,
        chosen_items,
        excluded_items,
    )
    plan = Plan(
        operation=operation,
        target=str(root),
        flavor=normalized_flavor,
        warnings=[target_note],
    )
    if excluded_items:
        plan.actions.append(
            {"action": "SKIP_COMPONENTS", "items": excluded_items}
        )
    if normalized_flavor in {"full", "extended"} and (
        chosen_items is None or "mcp:neo4j" in chosen_items
    ):
        plan.warnings.append(
            "Neo4j MCP requires NEO4J_PASSWORD in the Kiro process environment "
            "and in the IDE MCP Approved Env Vars list; never hard-code it."
        )
    candidate_paths = set(desired) | set(old_files)
    customized_scopes = set(previous_workspace_scopes)
    relinquished_scopes: set[str] = set()
    for relative in candidate_paths:
        scope = _customizable_workspace_scope(relative)
        if scope is None:
            continue
        path = safe_join(root, relative)
        if not path.exists():
            if relative in desired and relative in old_files:
                customized_scopes.add(scope)
                relinquished_scopes.add(scope)
            continue
        if not path.is_file() or path.is_symlink():
            continue
        actual = sha256_file(path)
        if relative in desired:
            wanted = sha256_bytes(desired[relative])
            if actual != wanted and (
                relative not in old_files or old_files[relative] != actual
            ):
                customized_scopes.add(scope)
                if relative in old_files:
                    relinquished_scopes.add(scope)
        elif actual != old_files[relative]:
            customized_scopes.add(scope)
            relinquished_scopes.add(scope)
    if customized_scopes:
        plan.warnings.append(
            "Preserved user-customized workspace items; AIDE relinquished ownership "
            "where previously managed: " + ", ".join(sorted(customized_scopes))
        )
        for scope in sorted(customized_scopes):
            plan.actions.append(
                {
                    "action": "RELINQUISH"
                    if scope in relinquished_scopes
                    else "PRESERVE",
                    "path": scope,
                    "reason": "user-controlled scope",
                }
            )
    final_hashes: dict[str, str] = {}
    write_files: dict[str, bytes] = {}
    for relative, content in sorted(desired.items()):
        path = safe_join(root, relative)
        wanted = sha256_bytes(content)
        scope = _customizable_workspace_scope(relative)
        if path.exists() and (not path.is_file() or path.is_symlink()):
            plan.conflicts.append({"path": relative, "reason": "not a regular file"})
            continue
        if scope in customized_scopes:
            continue
        final_hashes[relative] = wanted
        if not path.exists():
            plan.actions.append({"action": "ADD", "path": relative})
            write_files[relative] = content
        else:
            actual = sha256_file(path)
            if actual == wanted:
                plan.actions.append({"action": "PRESERVE", "path": relative})
            elif relative not in old_files:
                plan.conflicts.append(
                    {"path": relative, "reason": "existing file is not baseline-owned"}
                )
            elif old_files[relative] != actual:
                plan.conflicts.append(
                    {
                        "path": relative,
                        "reason": "baseline-owned file has local changes",
                    }
                )
            else:
                plan.actions.append({"action": "UPDATE", "path": relative})
                write_files[relative] = content
    obsolete = sorted(set(old_files) - set(desired))
    obsolete_removals: list[str] = []
    for relative in obsolete:
        path = safe_join(root, relative)
        scope = _customizable_workspace_scope(relative)
        if path.exists() and (not path.is_file() or path.is_symlink()):
            plan.conflicts.append(
                {"path": relative, "reason": "unsafe non-regular path; preserved"}
            )
            continue
        if scope in customized_scopes:
            continue
        if (
            path.exists()
            and path.is_file()
            and sha256_file(path) == old_files[relative]
        ):
            plan.actions.append({"action": "REMOVE", "path": relative})
            obsolete_removals.append(relative)
        elif path.exists():
            plan.conflicts.append(
                {"path": relative, "reason": "obsolete managed file has local changes"}
            )
    gitignore_original, gitignore_content = _existing_gitignore(root)
    if gitignore_original != gitignore_content:
        plan.actions.append(
            {"action": "MERGE", "path": ".gitignore", "ownership": "marked-block"}
        )
    previous_mcp_ownership = ownership.get("settings", {}).get(
        ".kiro/settings/mcp.json", {}
    )
    if not isinstance(previous_mcp_ownership, dict):
        previous_mcp_ownership = {}
    mcp_original, mcp_content, owned_keys, preserved_mcp, removed_mcp = _merge_mcp(
        root,
        source_root,
        selected_integrations,
        normalized_flavor,
        previous_mcp_ownership,
        previous_mcp_preserved,
        chosen_items,
    )
    if preserved_mcp:
        plan.warnings.append(
            "Preserved user-controlled MCP entries; AIDE relinquished ownership "
            "where previously managed: " + ", ".join(sorted(set(preserved_mcp)))
        )
        for name in sorted(set(preserved_mcp) & set(previous_mcp_ownership)):
            plan.actions.append(
                {
                    "action": "RELINQUISH",
                    "path": f".kiro/settings/mcp.json#mcpServers.{name}",
                    "reason": "user-controlled MCP entry",
                }
            )
    if mcp_content is not None and mcp_original != mcp_content:
        plan.actions.append(
            {
                "action": "MERGE",
                "path": ".kiro/settings/mcp.json",
                "keys": owned_keys,
                "remove_keys": removed_mcp,
            }
        )
    lean_ctx_asset = None
    if normalized_flavor == "extended" and "lean-ctx" in owned_keys:
        lean_ctx_asset = current_asset()
        if install_needed(root, lean_ctx_asset):
            plan.actions.append(
                {
                    "action": "INSTALL_VERIFIED_RUNTIME",
                    "path": lean_ctx_asset.binary_relative,
                    "source": lean_ctx_asset.url,
                    "archive_sha256": lean_ctx_asset.sha256,
                }
            )
    if plan.conflicts or not apply:
        return plan
    lean_ctx_payload = (
        prepare_binary(root, lean_ctx_asset)
        if lean_ctx_asset is not None and install_needed(root, lean_ctx_asset)
        else None
    )
    transaction = FileTransaction()
    try:
        if lean_ctx_payload is not None and lean_ctx_asset is not None:
            archive, binary = lean_ctx_payload
            transaction.write(safe_join(root, lean_ctx_asset.archive_relative), archive)
            binary_path = safe_join(root, lean_ctx_asset.binary_relative)
            transaction.write(binary_path, binary)
            verify_binary(binary_path, root)
        for relative, content in write_files.items():
            transaction.write(safe_join(root, relative), content)
        for relative in obsolete_removals:
            path = safe_join(root, relative)
            if path.exists():
                transaction.remove(path)
        if gitignore_original != gitignore_content:
            transaction.write(root / ".gitignore", gitignore_content)
        if mcp_content is not None and mcp_original != mcp_content:
            transaction.write(root / ".kiro" / "settings" / "mcp.json", mcp_content)
        previous_lock_path = root / ".aide" / "baseline.lock.json"
        previous_lock = (
            read_json(previous_lock_path) if previous_lock_path.exists() else {}
        )
        stable_selection = (
            previous_lock.get("baseline_version") == baseline_version(source_root)
            and previous_lock.get("flavor", "minimal") == normalized_flavor
            and previous_lock.get("profiles") == selected_profiles
            and previous_lock.get("integrations") == selected_integrations
            and previous_lock.get("components") == selected_components
            and previous_lock.get("kiro_target") == target_format
            and previous_lock.get("excluded_items", []) == excluded_items
        )
        lock = {
            "schema_version": 1,
            "baseline_version": baseline_version(source_root),
            "flavor": normalized_flavor,
            "installed_at": previous_lock.get("installed_at")
            if stable_selection
            else utc_now(),
            "profiles": selected_profiles,
            "integrations": selected_integrations,
            "components": selected_components,
            "excluded_items": excluded_items,
            "kiro_target": target_format,
            "source_manifest_hash": sha256_file(source_root / "manifest.json"),
        }
        merged_mcp = json.loads(mcp_content) if mcp_content is not None else {}
        merged_servers = merged_mcp.get("mcpServers", {})
        managed = {
            "schema_version": 1,
            "files": final_hashes,
            "settings": {
                ".kiro/settings/mcp.json": {
                    key: sha256_value(merged_servers[key]) for key in owned_keys
                }
            },
            "preserved": {
                "workspace_scopes": sorted(customized_scopes),
                "mcp_entries": sorted(set(preserved_mcp)),
            },
            "marked_blocks": {".gitignore": "AIDE-BASELINE"},
        }
        transaction.write(root / ".aide" / "baseline.lock.json", canonical_json(lock))
        managed["control_files"] = {
            ".aide/baseline.lock.json": sha256_bytes(canonical_json(lock))
        }
        transaction.write(
            root / ".aide" / "managed-files.json", canonical_json(managed)
        )
    except Exception:
        transaction.rollback()
        raise
    plan.applied = True
    return plan


def bootstrap(target: Path) -> dict[str, Any]:
    """Prepare ignored local state from committed configuration only."""

    root = find_git_root(target)
    project = read_json(safe_join(root, ".aide/project.json", allow_leaf_missing=False))
    validate_project(project)
    lock = read_json(
        safe_join(root, ".aide/baseline.lock.json", allow_leaf_missing=False)
    )
    local = safe_join(root, ".aide/local")
    if is_reparse_point(local):
        raise SafetyError(f"Refusing reparse-point local state: {local}")
    local.mkdir(parents=True, exist_ok=True)
    (local / "runs").mkdir(exist_ok=True)
    return {
        "status": "READY",
        "root": str(root),
        "baseline_version": lock["baseline_version"],
        "flavor": project.get("flavor", "minimal"),
        "profiles": project.get("profiles", []),
        "shared_configuration_rewritten": False,
    }


def uninstall(target: Path, *, apply: bool = False) -> Plan:
    """Remove only unchanged baseline-owned files, keys, and marked blocks."""

    root = find_git_root(target)
    ownership = _load_ownership(root)
    plan = Plan(operation="uninstall", target=str(root))
    removable: list[Path] = []
    owned_files = dict(ownership.get("files", {}))
    owned_files.update(ownership.get("control_files", {}))
    for relative, expected in sorted(owned_files.items()):
        path = safe_join(root, relative)
        if not path.exists():
            plan.actions.append(
                {"action": "PRESERVE", "path": relative, "reason": "already absent"}
            )
        elif path.is_file() and not path.is_symlink() and sha256_file(path) == expected:
            plan.actions.append({"action": "REMOVE", "path": relative})
            removable.append(path)
        else:
            plan.conflicts.append(
                {"path": relative, "reason": "changed or unsafe; preserved"}
            )
    mcp_path = safe_join(root, ".kiro/settings/mcp.json")
    owned_settings = ownership.get("settings", {}).get(".kiro/settings/mcp.json", {})
    if isinstance(owned_settings, list):
        owned_settings = {key: None for key in owned_settings}
    owned_keys = list(owned_settings)
    mcp_new: bytes | None = None
    if owned_keys and mcp_path.exists():
        if is_reparse_point(mcp_path):
            raise SafetyError(f"Refusing linked MCP settings file: {mcp_path}")
        value = read_json(mcp_path)
        removed_keys: list[str] = []
        for key in owned_keys:
            current = value.get("mcpServers", {}).get(key)
            expected = owned_settings[key]
            if current is None:
                continue
            if expected is not None and sha256_value(current) != expected:
                plan.conflicts.append(
                    {
                        "path": f".kiro/settings/mcp.json#mcpServers.{key}",
                        "reason": "owned MCP entry has local changes; preserved",
                    }
                )
                continue
            value.get("mcpServers", {}).pop(key, None)
            removed_keys.append(key)
        if removed_keys:
            mcp_new = canonical_json(value)
            plan.actions.append(
                {
                    "action": "MERGE",
                    "path": ".kiro/settings/mcp.json",
                    "remove_keys": removed_keys,
                }
            )
    ignore_path = root / ".gitignore"
    ignore_new: bytes | None = None
    if ignore_path.exists():
        if is_reparse_point(ignore_path):
            raise SafetyError(f"Refusing linked ignore file: {ignore_path}")
        text = ignore_path.read_text(encoding="utf-8")
        pattern = re.compile(
            re.escape(IGNORE_START) + r".*?" + re.escape(IGNORE_END) + r"\n?", re.S
        )
        replaced = pattern.sub("", text)
        if replaced != text:
            ignore_new = replaced.encode("utf-8")
            plan.actions.append(
                {
                    "action": "MERGE",
                    "path": ".gitignore",
                    "remove_block": "AIDE-BASELINE",
                }
            )
    # The ownership file is the final owned control removed.
    managed_path = root / ".aide" / "managed-files.json"
    if managed_path.exists():
        plan.actions.append({"action": "REMOVE", "path": ".aide/managed-files.json"})
    if not apply or plan.conflicts:
        return plan
    transaction = FileTransaction()
    try:
        for path in removable:
            transaction.remove(path)
        if mcp_new is not None:
            transaction.write(mcp_path, mcp_new)
        if ignore_new is not None:
            transaction.write(ignore_path, ignore_new)
        if managed_path.exists():
            transaction.remove(managed_path)
    except Exception:
        transaction.rollback()
        raise
    plan.applied = True
    return plan


def reset(
    target: Path,
    *,
    apply: bool = False,
    confirmation: str | None = None,
) -> Plan:
    """Remove the recorded installation footprint, including modified owned files.

    Reset is intentionally stronger than uninstall. It removes every regular file
    recorded as baseline-owned and every recorded MCP key without comparing current
    content with the last installed hash. Repository source, user-owned settings,
    and ignored ``.aide/local`` state are outside that ownership boundary.
    """

    root = find_git_root(target)
    ownership_path = safe_join(root, ".aide/managed-files.json")
    project_path = safe_join(root, ".aide/project.json")
    if not ownership_path.exists():
        return Plan(
            operation="reset",
            target=str(root),
            warnings=["No recorded AIDE installation was found; nothing to reset."],
        )
    ownership = _load_ownership(root)
    flavor = "minimal"
    warnings = [
        "Reset removes locally modified baseline-owned files and MCP entries. "
        "Application files, user-owned MCP entries, and .aide/local are preserved."
    ]
    if project_path.exists():
        try:
            project = read_json(project_path)
            flavor = project.get("flavor", "minimal")
        except ConfigurationError:
            warnings.append(
                "The installed project descriptor is invalid; ownership data will "
                "still be used for reset."
            )
    plan = Plan(
        operation="reset",
        target=str(root),
        flavor=flavor,
        warnings=warnings,
    )
    removable: list[Path] = []
    owned_files = dict(ownership.get("files", {}))
    owned_files.update(ownership.get("control_files", {}))
    for relative in sorted(owned_files):
        path = safe_join(root, relative)
        if not path.exists():
            plan.actions.append(
                {"action": "PRESERVE", "path": relative, "reason": "already absent"}
            )
        elif path.is_file() and not path.is_symlink():
            plan.actions.append({"action": "REMOVE", "path": relative})
            removable.append(path)
        else:
            plan.conflicts.append(
                {"path": relative, "reason": "unsafe non-regular path; preserved"}
            )

    mcp_path = safe_join(root, ".kiro/settings/mcp.json")
    owned_settings = ownership.get("settings", {}).get(".kiro/settings/mcp.json", {})
    if isinstance(owned_settings, list):
        owned_settings = {key: None for key in owned_settings}
    owned_keys = list(owned_settings) if isinstance(owned_settings, dict) else []
    mcp_new: bytes | None = None
    if owned_keys and mcp_path.exists():
        if is_reparse_point(mcp_path):
            raise SafetyError(f"Refusing linked MCP settings file: {mcp_path}")
        value = read_json(mcp_path)
        servers = value.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ConfigurationError("Existing mcpServers value must be a JSON object.")
        removed_keys = [key for key in owned_keys if key in servers]
        for key in removed_keys:
            servers.pop(key)
        if removed_keys:
            mcp_new = canonical_json(value)
            plan.actions.append(
                {
                    "action": "MERGE",
                    "path": ".kiro/settings/mcp.json",
                    "remove_keys": removed_keys,
                }
            )

    ignore_path = root / ".gitignore"
    ignore_new: bytes | None = None
    if ignore_path.exists():
        if is_reparse_point(ignore_path):
            raise SafetyError(f"Refusing linked ignore file: {ignore_path}")
        text = ignore_path.read_text(encoding="utf-8")
        pattern = re.compile(
            re.escape(IGNORE_START) + r".*?" + re.escape(IGNORE_END) + r"\n?", re.S
        )
        replaced = pattern.sub("", text)
        if replaced != text:
            ignore_new = replaced.encode("utf-8")
            plan.actions.append(
                {
                    "action": "MERGE",
                    "path": ".gitignore",
                    "remove_block": "AIDE-BASELINE",
                }
            )

    plan.actions.append({"action": "REMOVE", "path": ".aide/managed-files.json"})
    if not apply:
        return plan
    if confirmation != "RESET":
        raise SafetyError("Reset apply requires --confirm RESET.")
    if plan.conflicts:
        return plan
    transaction = FileTransaction()
    try:
        for path in removable:
            transaction.remove(path)
        if mcp_new is not None:
            transaction.write(mcp_path, mcp_new)
        if ignore_new is not None:
            transaction.write(ignore_path, ignore_new)
        transaction.remove(ownership_path)
    except Exception:
        transaction.rollback()
        raise
    plan.applied = True
    return plan
