"""Deterministic Kiro hook handlers for the AIDE workflow."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MAX_EVENT_BYTES = 1_048_576
MAX_TEXT = 2_000
SENSITIVE_KEY = re.compile(
    r"(?i)^(authorization|cookie|credentials?|password|passwd|secret|"
    r"(?:access[_-]?)?token|api[_-]?key|pat)$"
)
SENSITIVE_VALUE = re.compile(
    r"(?i)(bearer\s+\S+|(?:ghp|glpat|sk)-[A-Za-z0-9_.-]+|"
    r"(?:password|secret|token|api[_-]?key)\s*[=:]\s*\S+)"
)
WRITE_TOOLS = {
    "write",
    "write_file",
    "edit",
    "edit_file",
    "apply_patch",
    "fs_write",
    "create_file",
    "delete_file",
    "move_file",
}
MUTATING_SHELL = re.compile(
    r"(?ix)(^|[;&|]\s*)"
    r"(git\s+(add|commit|push|reset|checkout|switch|branch|merge|rebase|tag)|"
    r"kubectl\s+(apply|create|delete|edit|patch|replace|rollout|scale|set)|"
    r"helm\s+(install|upgrade|uninstall|rollback)|"
    r"ansible-playbook\b|terraform\s+(apply|destroy|import)|"
    r"curl\b[^\r\n]*(?:-X|--request)\s*(POST|PUT|PATCH|DELETE)|"
    r"invoke-(restmethod|webrequest)\b[^\r\n]*-method\s*(POST|PUT|PATCH|DELETE)|"
    r"remove-item\b|move-item\b|copy-item\b|new-item\b|set-content\b|"
    r"add-content\b|rm\b|mv\b|cp\b|mkdir\b|touch\b)"
)
OPERATIONAL_SHELL = re.compile(
    r"(?i)\b(kubectl|helm|ansible(?:-playbook)?|terraform|curl|"
    r"invoke-restmethod|invoke-webrequest|git|az)\b"
)
MUTATING_MCP = re.compile(
    r"(?i)(create|write|edit|update|delete|remove|apply|patch|scale|deploy|"
    r"execute|run_query|commit|push|merge|close|open_issue|send)"
)
DELEGATION_TOOL = re.compile(
    r"(?i)(delegate|subagent|spawn[_-]?agent|handoff|create[_-]?thread|"
    r"send[_-]?message[_-]?to[_-]?thread)"
)
READ_QUERY = re.compile(r"(?is)^\s*(select|show|describe|explain|match\b.*return)\b")
JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+$")
JIRA_STORY = re.compile(
    r"^jira/(?P<key>[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+)-"
    r"(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md$"
)
AUTHORING_PHASES = {"jira-intake", "story-ready", "spec-authoring"}
MAX_SPEC_ATTEMPTS = 3


@dataclass(frozen=True)
class Settings:
    """Resolved workspace, policy, and state locations."""

    package_root: Path
    workspace_root: Path
    policy_path: Path
    state_dir: Path

    @classmethod
    def load(cls) -> Settings:
        """Resolve locations from environment variables and safe defaults."""
        package_root = Path(__file__).resolve().parents[2]
        workspace_root = Path(os.environ.get("AIDE_WORKSPACE_ROOT", Path.cwd()))
        policy_path = Path(
            os.environ.get("AIDE_HOOK_POLICY", package_root / "policy.json")
        )
        state_dir = Path(os.environ.get("AIDE_HOOK_STATE_DIR", package_root / ".state"))
        return cls(
            package_root=package_root,
            workspace_root=workspace_root.resolve(),
            policy_path=policy_path.resolve(),
            state_dir=state_dir.resolve(),
        )


class StateStore:
    """Small, atomic JSON and JSON Lines store; no database is required."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)

    def load(self, name: str, default: Any) -> Any:
        """Load a JSON document, returning the supplied default when absent."""
        path = self.settings.state_dir / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def save(self, name: str, value: Any) -> None:
        """Atomically replace a JSON document."""
        target = self.settings.state_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            delete=False,
            newline="\n",
        ) as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, target)

    def append(self, name: str, value: Any) -> None:
        """Append a compact record to a JSON Lines file."""
        target = self.settings.state_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")

    def tail(self, name: str, limit: int = 50) -> list[dict[str, Any]]:
        """Read the newest valid JSON Lines records."""
        target = self.settings.state_dir / name
        if not target.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in target.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records


def now() -> str:
    """Return a stable UTC timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def digest(value: str) -> str:
    """Return a short SHA-256 identifier for non-secret state comparison."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def load_policy(settings: Settings) -> dict[str, Any]:
    """Load policy and fail closed to an empty policy."""
    try:
        value = json.loads(settings.policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    git_policy = value.get("operations", {}).get("git", {})
    repositories = git_policy.get("repositories", [])
    git_policy["repositories"] = [
        settings.workspace_root.as_posix()
        if repository == "${workspace}"
        else repository
        for repository in repositories
    ]
    return value


def read_event(stream: Any = sys.stdin) -> dict[str, Any]:
    """Read one bounded Kiro event JSON object from standard input."""
    raw = stream.read(MAX_EVENT_BYTES + 1)
    if len(raw.encode("utf-8", errors="ignore")) > MAX_EVENT_BYTES:
        return {"_aide_error": "event exceeded one MiB and was discarded"}
    if not raw.strip():
        return {}
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return {"_aide_error": "event was not valid JSON"}
    return event if isinstance(event, dict) else {}


def redact(value: Any, key: str = "") -> Any:
    """Redact secret-shaped keys and values and bound retained evidence."""
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value[:100]]
    if isinstance(value, str):
        text = SENSITIVE_VALUE.sub("[REDACTED]", value)
        return text[:MAX_TEXT] + ("…" if len(text) > MAX_TEXT else "")
    return value


def find_value(value: Any, keys: set[str]) -> Any:
    """Find the first value whose normalized key matches one of the keys."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in keys:
                return item
        for item in value.values():
            found = find_value(item, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_value(item, keys)
            if found is not None:
                return found
    return None


def tool_name(event: dict[str, Any]) -> str:
    """Extract the triggering tool name without trusting one event version."""
    value = find_value(event, {"toolname", "tool"})
    return str(value or "").strip()


def tool_input(event: dict[str, Any]) -> Any:
    """Extract the tool input payload."""
    value = find_value(event, {"toolinput", "arguments", "input"})
    return value if value is not None else {}


def command_text(event: dict[str, Any]) -> str:
    """Extract a command or query from a tool event."""
    payload = tool_input(event)
    if isinstance(payload, str):
        return payload
    value = find_value(
        payload,
        {"command", "cmd", "script", "query", "cypher", "statement"},
    )
    return str(value or "")


def extract_paths(event: dict[str, Any]) -> list[str]:
    """Extract normalized path-like tool arguments."""
    results: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                normalized = re.sub(r"[^a-z0-9]", "", str(child_key).lower())
                if normalized in {
                    "path",
                    "filepath",
                    "filename",
                    "targetpath",
                    "destination",
                } and isinstance(child, str):
                    results.append(child)
                elif normalized == "files" and isinstance(child, list):
                    results.extend(str(item) for item in child if isinstance(item, str))
                else:
                    visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    visit(tool_input(event))
    return list(dict.fromkeys(item for item in results if item))[:100]


def git(settings: Settings, *args: str) -> str:
    """Run a bounded, read-only Git query."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=settings.workspace_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()[:10_000] or "unknown"


def inside_workspace(settings: Settings, raw_path: str) -> tuple[bool, str]:
    """Resolve a path and state whether it remains inside the workspace."""
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = settings.workspace_root / candidate
    try:
        resolved = candidate.resolve()
        relative = resolved.relative_to(settings.workspace_root)
    except (OSError, ValueError):
        return False, str(candidate)
    return True, relative.as_posix() or "."


def shell_is_preparation(command: str, policy: dict[str, Any]) -> bool:
    """Return true only for an explicitly allowlisted preparation command."""
    compact = " ".join(command.strip().split()).lower()
    for pattern in policy.get("preparation_commands", []):
        if fnmatch.fnmatchcase(compact, str(pattern).lower()):
            return True
    return False


def query_is_mutating(command: str) -> bool:
    """Conservatively identify a database query as mutating."""
    if not command.strip():
        return True
    return READ_QUERY.match(command) is None


def classify_operation(
    event: dict[str, Any], settings: Settings, policy: dict[str, Any]
) -> dict[str, Any]:
    """Classify target, mutation, protection, and operational authorization."""
    name = tool_name(event)
    lower_name = name.lower()
    command = command_text(event)
    paths = extract_paths(event)
    reasons: list[str] = []
    targets: list[str] = []
    protected = lower_name in WRITE_TOOLS
    operational = False
    mutation = protected
    category = "local"

    if "shell" in lower_name or lower_name in {"execute_bash", "powershell"}:
        mutation = bool(MUTATING_SHELL.search(command))
        operational = bool(OPERATIONAL_SHELL.search(command))
        protected = bool(command.strip())

    if DELEGATION_TOOL.search(lower_name):
        mutation = True
        protected = True
        targets.append(f"delegation:{lower_name}")

    if lower_name.startswith("@") or "mcp" in lower_name:
        operational = True
        mutation = bool(MUTATING_MCP.search(lower_name))
        if any(token in lower_name for token in ("postgres", "neo4j", "database")):
            mutation = mutation or query_is_mutating(command)
        protected = mutation

    if shell_is_preparation(command, policy):
        protected = False
        mutation = False

    if protected and command and not operational and not paths:
        targets.append("execution:workspace")

    for raw_path in paths:
        valid, normalized = inside_workspace(settings, raw_path)
        if valid:
            targets.append(f"file:{normalized}")
        else:
            reasons.append(f"path is outside workspace: {raw_path}")

    text = f"{lower_name} {command}".lower()
    if "aide-azure-change-mcp" in lower_name:
        category = "azure"
        operational = True
        if mutation:
            plan_id = str(find_value(event, {"planid"}) or "")
            if AZURE_CHANGE_PLAN_ID.fullmatch(plan_id):
                targets.append(f"azure-plan:{plan_id}")
            else:
                reasons.append("Azure apply plan ID is missing or invalid")
            allowed_tools = (
                policy.get("operations", {}).get("mcp", {}).get("mutating_tools", [])
            )
            if not _matches_any(lower_name, allowed_tools):
                reasons.append(f"mutating MCP tool is not authorized: {name}")
    elif "aide-kubernetes-change-mcp" in lower_name:
        category = "kubernetes"
        operational = True
        if mutation:
            plan_id = str(find_value(event, {"planid"}) or "")
            if KUBERNETES_CHANGE_PLAN_ID.fullmatch(plan_id):
                targets.append(f"kubernetes-plan:{plan_id}")
            else:
                reasons.append("Kubernetes apply plan ID is missing or invalid")
            allowed_tools = (
                policy.get("operations", {}).get("mcp", {}).get("mutating_tools", [])
            )
            if not _matches_any(lower_name, allowed_tools):
                reasons.append(f"mutating MCP tool is not authorized: {name}")
    elif "aide-kubernetes-mcp" in lower_name:
        category = "kubernetes"
        operational = True
        targets.append("kubernetes:configured-target")
    elif "kubectl" in text or "kubernetes" in text:
        category = "kubernetes"
        operational = True
        context = _flag_or_field(command, event, "context")
        namespace = _flag_or_field(command, event, "namespace", short="n")
        if not context:
            context = gitless_command(
                settings,
                ["kubectl", "config", "current-context"],
            )
        if not namespace:
            namespace = gitless_command(
                settings,
                [
                    "kubectl",
                    "config",
                    "view",
                    "--minify",
                    "--output",
                    "jsonpath={..namespace}",
                ],
            )
        if (
            not context
            or context == "unknown"
            or not namespace
            or namespace == "unknown"
        ):
            reasons.append("Kubernetes context and namespace must both be known")
        else:
            targets.append(f"kubernetes:{context}/{namespace}")
            allowed = policy.get("operations", {}).get("kubernetes", {})
            if not _matches_any(context, allowed.get("contexts", [])):
                reasons.append(f"Kubernetes context is not authorized: {context}")
            if not _matches_any(namespace, allowed.get("namespaces", [])):
                reasons.append(f"Kubernetes namespace is not authorized: {namespace}")
            if mutation and not allowed.get("allow_mutations", False):
                reasons.append("Kubernetes mutations are disabled by policy")
    elif "ansible" in text:
        category = "ansible"
        operational = True
        inventory = _flag(command, "inventory", short="i") or str(
            find_value(event, {"inventory"}) or ""
        )
        if not inventory:
            reasons.append("Ansible inventory must be explicit")
        else:
            targets.append(f"ansible:{inventory}")
            allowed = policy.get("operations", {}).get("ansible", {})
            if not _matches_any(inventory, allowed.get("inventories", [])):
                reasons.append(f"Ansible inventory is not authorized: {inventory}")
            if mutation and not allowed.get("allow_mutations", False):
                reasons.append("Ansible execution is disabled by policy")
    elif re.search(r"(?i)\b(curl|invoke-restmethod|invoke-webrequest)\b", text):
        category = "http"
        operational = True
        url_match = re.search(r"https?://[^\s'\"]+", command)
        host = urlparse(url_match.group(0)).hostname if url_match else None
        if not host:
            reasons.append("HTTP endpoint host must be explicit")
        else:
            targets.append(f"url:{host}")
            allowed = policy.get("operations", {}).get("http", {})
            if not _matches_any(host, allowed.get("hosts", [])):
                reasons.append(f"HTTP host is not authorized: {host}")
            if mutation and not allowed.get("allow_live_mutations", False):
                reasons.append("live HTTP mutations are disabled by policy")
    elif re.search(r"(?i)\bgit\b", text) or "@git" in lower_name:
        category = "git"
        repository = git(settings, "rev-parse", "--show-toplevel")
        branch = git(settings, "branch", "--show-current")
        action_match = re.search(
            r"(?i)\bgit\s+(add|commit|push|reset|checkout|switch|branch|merge|rebase|tag)",
            command,
        )
        action = action_match.group(1).lower() if action_match else lower_name
        if repository == "unknown" or branch == "unknown":
            reasons.append("Git repository and branch must both be known")
        else:
            targets.append(f"git:{Path(repository).as_posix()}#{branch}:{action}")
            allowed = policy.get("operations", {}).get("git", {})
            roots = allowed.get("repositories", [])
            if not _matches_any(Path(repository).as_posix(), roots):
                reasons.append(f"Git repository is not authorized: {repository}")
            if not _matches_any(branch, allowed.get("branches", [])):
                reasons.append(f"Git branch is not authorized: {branch}")
            if mutation and not _matches_any(action, allowed.get("actions", [])):
                reasons.append(f"Git action is not authorized: {action}")
    elif operational and mutation:
        category = "mcp"
        targets.append(f"mcp:{lower_name or 'unknown'}")
        allowed_tools = (
            policy.get("operations", {}).get("mcp", {}).get("mutating_tools", [])
        )
        if not _matches_any(lower_name, allowed_tools):
            reasons.append(f"mutating MCP tool is not authorized: {name or 'unknown'}")

    if mutation and paths and not targets:
        reasons.append("a protected path target could not be resolved")
    if protected and not targets and category == "local":
        reasons.append("protected action target is unknown")

    return {
        "authorized": not reasons,
        "category": category,
        "mutation": mutation,
        "operational": operational,
        "protected": protected,
        "reasons": reasons,
        "targets": list(dict.fromkeys(targets)),
        "tool": name or "unknown",
    }


AZURE_CHANGE_PLAN_ID = re.compile(r"^[a-f0-9]{32}$")
AZURE_CHANGE_TOOLS = {
    "aide_azure_change_status",
    "aide_validate_azure_deployment",
    "aide_plan_azure_deployment",
    "aide_apply_azure_deployment",
    "aide_get_azure_deployment_status",
}
AZURE_MCP_TOOLS = {
    "aide_azure_status",
    "aide_verify_azure_context",
    "aide_list_resource_group_resources",
    "aide_list_recent_azure_activity",
    "aide_list_azure_metric_definitions",
    "aide_query_azure_metrics",
    "aide_list_foundry_deployments",
    "aide_list_acr_repositories",
    "aide_list_acr_tags",
}
AZURE_CLI = re.compile(r"(?i)(?:^|[;&|]\s*|[\\/])az(?:\.cmd|\.exe)?(?:['\"]?\s|$)")

KUBERNETES_CHANGE_PLAN_ID = re.compile(r"^[a-f0-9]{32}$")
KUBERNETES_CHANGE_TOOLS = {
    "aide_kubernetes_change_status",
    "aide_validate_kubernetes_manifest",
    "aide_plan_kubernetes_apply",
    "aide_apply_kubernetes_manifest",
    "aide_get_kubernetes_change_status",
}
KUBERNETES_MCP_TOOLS = {
    "aide_kubernetes_status",
    "aide_verify_kubernetes_context",
    "aide_list_kubernetes_workloads",
    "aide_list_kubernetes_networking",
    "aide_list_kubernetes_events",
    "aide_read_kubernetes_resource",
    "aide_read_kubernetes_pod_logs",
}
KUBECTL = re.compile(r"(?i)(?:^|[;&|]\s*|[\/])kubectl(?:\.exe)?(?:\s|$)")


def classify_azure_access(event: dict[str, Any]) -> dict[str, Any]:
    """Allow bounded Azure MCP tools and only harmless direct context checks."""
    name = tool_name(event)
    lower_name = name.lower()
    command = command_text(event).strip()
    if "aide-azure-mcp" in lower_name:
        matched = next((tool for tool in AZURE_MCP_TOOLS if tool in lower_name), None)
        return {
            "applicable": True,
            "authorized": matched is not None,
            "reason": "bounded Azure MCP tool" if matched else "unknown Azure MCP tool",
            "tool": name or "unknown",
        }
    if not AZURE_CLI.search(command):
        return {
            "applicable": False,
            "authorized": True,
            "reason": "not an Azure operation",
            "tool": name or "unknown",
        }
    if re.search(r"[;&|]", command):
        return {
            "applicable": True,
            "authorized": False,
            "reason": "compound Azure CLI commands are not allowed",
            "tool": name or "unknown",
        }
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        tokens = []
    words = [token.strip("'\"").lower() for token in tokens]
    while words and words[-1] in {"json", "jsonc", "table", "tsv", "yaml", "yamlc"}:
        if len(words) >= 2 and words[-2] in {"--output", "-o"}:
            words = words[:-2]
        else:
            break
    words = [word for word in words if word != "--only-show-errors"]
    direct_allowed = words in (["az", "version"], ["az", "account", "show"])
    return {
        "applicable": True,
        "authorized": direct_allowed,
        "reason": (
            "local Azure CLI context check"
            if direct_allowed
            else "use the bounded aide-azure-mcp tools for Azure observations"
        ),
        "tool": name or "unknown",
    }


def classify_azure_change(event: dict[str, Any]) -> dict[str, Any]:
    """Allow only the fixed Azure change MCP surface and validate apply plan ID."""
    name = tool_name(event)
    lower_name = name.lower()
    if "aide-azure-change-mcp" not in lower_name:
        return {
            "applicable": False,
            "authorized": True,
            "mutation": False,
            "reason": "not an Azure change MCP operation",
            "tool": name or "unknown",
        }
    matched = next((tool for tool in AZURE_CHANGE_TOOLS if tool in lower_name), None)
    mutation = matched == "aide_apply_azure_deployment"
    plan_id = str(find_value(event, {"planid"}) or "") if mutation else ""
    authorized = matched is not None and (
        not mutation or AZURE_CHANGE_PLAN_ID.fullmatch(plan_id) is not None
    )
    return {
        "applicable": True,
        "authorized": authorized,
        "mutation": mutation,
        "plan_id": plan_id or None,
        "reason": (
            "known Azure change MCP tool"
            if authorized
            else "unknown Azure change tool or invalid apply plan ID"
        ),
        "tool": name or "unknown",
    }


def classify_kubernetes_access(event: dict[str, Any]) -> dict[str, Any]:
    """Allow fixed observer tools and only harmless direct local kubectl checks."""
    name = tool_name(event)
    lower_name = name.lower()
    command = command_text(event).strip()
    if "aide-kubernetes-change-mcp" in lower_name:
        return {
            "applicable": False,
            "authorized": True,
            "reason": "Kubernetes change MCP is handled separately",
            "tool": name or "unknown",
        }
    if "aide-kubernetes-mcp" in lower_name:
        matched = next(
            (tool for tool in KUBERNETES_MCP_TOOLS if tool in lower_name), None
        )
        return {
            "applicable": True,
            "authorized": matched is not None,
            "reason": (
                "bounded Kubernetes MCP tool"
                if matched
                else "unknown Kubernetes observation MCP tool"
            ),
            "tool": name or "unknown",
        }
    if not KUBECTL.search(command):
        return {
            "applicable": False,
            "authorized": True,
            "reason": "not a Kubernetes operation",
            "tool": name or "unknown",
        }
    if re.search(r"[;&|]", command):
        return {
            "applicable": True,
            "authorized": False,
            "reason": "compound kubectl commands are not allowed",
            "tool": name or "unknown",
        }
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        tokens = []
    words = [token.strip("'\"").lower() for token in tokens]
    direct_allowed = words in (
        ["kubectl", "config", "current-context"],
        ["kubectl", "version", "--client"],
        ["kubectl", "version", "--client", "--output=json"],
    )
    return {
        "applicable": True,
        "authorized": direct_allowed,
        "reason": (
            "local kubectl context/client check"
            if direct_allowed
            else "use the bounded aide-kubernetes-mcp tools for cluster observation"
        ),
        "tool": name or "unknown",
    }


def classify_kubernetes_change(event: dict[str, Any]) -> dict[str, Any]:
    """Allow only fixed change tools and validate apply plan IDs."""
    name = tool_name(event)
    lower_name = name.lower()
    if "aide-kubernetes-change-mcp" not in lower_name:
        return {
            "applicable": False,
            "authorized": True,
            "mutation": False,
            "reason": "not a Kubernetes change MCP operation",
            "tool": name or "unknown",
        }
    matched = next(
        (tool for tool in KUBERNETES_CHANGE_TOOLS if tool in lower_name), None
    )
    mutation = matched == "aide_apply_kubernetes_manifest"
    plan_id = str(find_value(event, {"planid"}) or "") if mutation else ""
    authorized = matched is not None and (
        not mutation or KUBERNETES_CHANGE_PLAN_ID.fullmatch(plan_id) is not None
    )
    return {
        "applicable": True,
        "authorized": authorized,
        "mutation": mutation,
        "plan_id": plan_id or None,
        "reason": (
            "known Kubernetes change MCP tool"
            if authorized
            else "unknown Kubernetes change tool or invalid apply plan ID"
        ),
        "tool": name or "unknown",
    }


def handle_kubernetes_read_only(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Fail closed for unbounded agent-driven Kubernetes access."""
    decision = classify_kubernetes_access(event)
    store.append(
        "events.jsonl",
        {"hook": "aide-kubernetes-read-only", **decision, "at": now()},
    )
    if decision["applicable"] and not decision["authorized"]:
        print("AIDE Kubernetes read-only blocked: " + str(decision["reason"]))
        return 2
    print("AIDE Kubernetes read-only: " + str(decision["reason"]))
    return 0


def handle_kubernetes_observation(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Record Kubernetes metadata without cluster response payloads."""
    record = event_record("aide-kubernetes-observation-evidence", event, settings)
    record.pop("command", None)
    store.append("kubernetes-observations.jsonl", record)
    print("AIDE Kubernetes observation evidence recorded without response content")
    return 0


def handle_kubernetes_change_control(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Fail closed before unknown Kubernetes change tools or malformed apply."""
    decision = classify_kubernetes_change(event)
    store.append(
        "events.jsonl",
        {"hook": "aide-kubernetes-change-control", **decision, "at": now()},
    )
    if decision["applicable"] and not decision["authorized"]:
        print("AIDE Kubernetes change blocked: " + str(decision["reason"]))
        return 2
    print("AIDE Kubernetes change: " + str(decision["reason"]))
    return 0


def handle_kubernetes_change_evidence(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Record change metadata without manifest or cluster payloads."""
    decision = classify_kubernetes_change(event)
    record = event_record("aide-kubernetes-change-evidence", event, settings)
    record.pop("command", None)
    record["mutation"] = decision["mutation"]
    record["plan_id"] = decision["plan_id"]
    store.append("kubernetes-changes.jsonl", record)
    print("AIDE Kubernetes change evidence recorded without response content")
    return 0


def handle_azure_change_control(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Fail closed before unknown Azure change tools or malformed apply calls."""
    decision = classify_azure_change(event)
    store.append(
        "events.jsonl", {"hook": "aide-azure-change-control", **decision, "at": now()}
    )
    if decision["applicable"] and not decision["authorized"]:
        print("AIDE Azure change blocked: " + str(decision["reason"]))
        return 2
    print("AIDE Azure change: " + str(decision["reason"]))
    return 0


def handle_azure_change_evidence(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Record Azure change metadata without output, parameters, or cloud payloads."""
    decision = classify_azure_change(event)
    record = event_record("aide-azure-change-evidence", event, settings)
    record.pop("command", None)
    record["mutation"] = decision["mutation"]
    record["plan_id"] = decision["plan_id"]
    store.append("azure-changes.jsonl", record)
    print("AIDE Azure change evidence recorded without response content")
    return 0


def handle_azure_read_only(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Fail closed for unbounded or mutating agent-driven Azure access."""
    decision = classify_azure_access(event)
    store.append(
        "events.jsonl", {"hook": "aide-azure-read-only", **decision, "at": now()}
    )
    if decision["applicable"] and not decision["authorized"]:
        print("AIDE Azure read-only blocked: " + str(decision["reason"]))
        return 2
    print("AIDE Azure read-only: " + str(decision["reason"]))
    return 0


def handle_azure_observation(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Record Azure tool metadata without persisting cloud response payloads."""
    record = event_record("aide-azure-observation-evidence", event, settings)
    record.pop("command", None)
    store.append("azure-observations.jsonl", record)
    print("AIDE Azure observation evidence recorded without response content")
    return 0


def _matches_any(value: str, patterns: list[Any]) -> bool:
    return any(
        fnmatch.fnmatchcase(value.lower(), str(pattern).lower()) for pattern in patterns
    )


def _flag(command: str, long: str, short: str | None = None) -> str:
    flags = [rf"--{re.escape(long)}(?:=|\s+)([^\s]+)"]
    if short:
        flags.append(rf"-{re.escape(short)}\s+([^\s]+)")
    for pattern in flags:
        match = re.search(pattern, command)
        if match:
            return match.group(1).strip("'\"")
    return ""


def _flag_or_field(
    command: str, event: dict[str, Any], long: str, short: str | None = None
) -> str:
    return _flag(command, long, short) or str(
        find_value(event, {re.sub(r"[^a-z0-9]", "", long.lower())}) or ""
    )


def gitless_command(settings: Settings, args: list[str]) -> str:
    """Run a bounded read-only target-discovery command."""
    try:
        result = subprocess.run(
            args,
            cwd=settings.workspace_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip()[:500] if result.returncode == 0 else "unknown"


def evidence_status(event: dict[str, Any]) -> str:
    """Derive a conservative evidence status from observable output."""
    error = find_value(event, {"error", "stderr", "failure"})
    exit_code = find_value(event, {"exitcode", "statuscode"})
    if error or (isinstance(exit_code, int) and exit_code != 0):
        return "failed"
    if exit_code == 0 or find_value(event, {"success"}) is True:
        return "passed"
    if not event:
        return "not_run"
    return "unknown"


def input_shape(value: Any) -> dict[str, Any]:
    """Describe tool input without retaining source, records, or prompt content."""
    if isinstance(value, dict):
        return {
            "keys": sorted(str(key) for key in value.keys())[:50],
            "type": "object",
        }
    if isinstance(value, list):
        return {"item_count": min(len(value), 100), "type": "array"}
    if isinstance(value, str):
        return {"character_count": min(len(value), MAX_TEXT), "type": "string"}
    return {"type": type(value).__name__}


def event_record(
    hook: str, event: dict[str, Any], settings: Settings
) -> dict[str, Any]:
    """Create a bounded evidence record without retaining full conversation text."""
    payload = tool_input(event)
    delegated = bool(
        re.search(r"(?i)(delegate|subagent|agent)", tool_name(event))
        or find_value(event, {"delegated"}) is True
    )
    command = command_text(event)
    return {
        "changed_artifacts": extract_paths(event),
        "command": redact(command) if command else None,
        "delegated": delegated,
        "hook": hook,
        "revision": git(settings, "rev-parse", "HEAD"),
        "status": evidence_status(event),
        "timestamp": now(),
        "tool": tool_name(event) or "unknown",
        "tool_input_summary": input_shape(payload),
    }


def handle_safe_operation(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Block operational actions whose actual target is unknown or unauthorized."""
    operation = classify_operation(event, settings, load_policy(settings))
    store.append(
        "events.jsonl", {"hook": "aide-safe-operation", **operation, "at": now()}
    )
    if operation["operational"] and not operation["authorized"]:
        print("AIDE safe-operation blocked: " + "; ".join(operation["reasons"]))
        return 2
    print(
        "AIDE safe-operation: "
        + (
            "authorized target verified"
            if operation["operational"]
            else "not operational"
        )
    )
    return 0


def _target_allowed(actual: str, approved: list[Any]) -> bool:
    return _matches_any(actual, approved)


def _is_authoring_operation(
    operation: dict[str, Any], workflow: dict[str, Any]
) -> bool:
    """Allow only the active story or specification authoring target."""
    if workflow.get("phase") not in AUTHORING_PHASES:
        return False
    if operation["operational"] or not operation["mutation"]:
        return False
    actual_targets = operation.get("targets", [])
    allowed_targets = workflow.get("authoring_targets", [])
    return bool(actual_targets) and all(
        _target_allowed(target, allowed_targets) for target in actual_targets
    )


def handle_approval_gate(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Require current explicit approval before a protected action."""
    policy = load_policy(settings)
    operation = classify_operation(event, settings, policy)
    if not operation["protected"]:
        print("AIDE approval-gate: unprotected or approved preparation action")
        return 0
    workflow = store.load("workflow.json", {})
    if _is_authoring_operation(operation, workflow):
        print("AIDE approval-gate: active authoring target verified")
        return 0
    approvals = store.load("approvals.json", {})
    gate = "operations" if operation["operational"] else "implementation"
    approval = approvals.get(gate, {}) if isinstance(approvals, dict) else {}
    problems: list[str] = []
    if not workflow:
        problems.append("workflow state is not initialized")
    if approval.get("decision") != "approve":
        problems.append(f"explicit {gate} approval is missing")
    for key in ("task_id", "plan_revision", "scope_hash"):
        if workflow.get(key) != approval.get(key):
            problems.append(f"approval {key} does not match current workflow")
    actual_targets = operation["targets"]
    approved_targets = approval.get("targets", [])
    if not actual_targets:
        problems.append("protected action target is unknown")
    for target in actual_targets:
        if not _target_allowed(target, approved_targets):
            problems.append(f"target is outside approval: {target}")
    if problems:
        print("AIDE approval-gate blocked: " + "; ".join(dict.fromkeys(problems)))
        return 2
    print(f"AIDE approval-gate: current {gate} approval verified")
    return 0


def spec_readiness(workflow: dict[str, Any], settings: Settings) -> list[str]:
    """Return structural and review gaps for normal or lightweight specs."""
    gaps: list[str] = []
    if not workflow:
        return ["workflow state is not initialized"]
    if not workflow.get("spec_reviewed", False):
        gaps.append("specification has not received explicit human review approval")
    mode = workflow.get("change_class", "normal")
    if mode == "small":
        if not workflow.get("lightweight_approved", False):
            gaps.append("small-change path is not explicitly approved")
        raw_path = workflow.get("lightweight_spec", "")
        if not raw_path:
            gaps.append("lightweight specification path is missing")
        else:
            valid, relative = inside_workspace(settings, raw_path)
            path = settings.workspace_root / relative if valid else Path(raw_path)
            if not valid or not path.is_file() or path.stat().st_size < 50:
                gaps.append("lightweight specification is absent or too small")
        return gaps

    raw_dir = workflow.get("spec_dir", "")
    if not raw_dir:
        return gaps + ["specification directory is missing"]
    valid, relative = inside_workspace(settings, raw_dir)
    if not valid:
        return gaps + ["specification directory is outside the workspace"]
    spec_dir = settings.workspace_root / relative
    files = {
        "requirements": spec_dir / "requirements.md",
        "design": spec_dir / "design.md",
        "tasks": spec_dir / "tasks.md",
    }
    contents: dict[str, str] = {}
    for label, path in files.items():
        if not path.is_file() or path.stat().st_size < 50:
            gaps.append(f"{label}.md is absent or too small")
            contents[label] = ""
        else:
            contents[label] = path.read_text(encoding="utf-8", errors="replace")
    if contents.get("requirements") and not re.search(
        r"(?i)(acceptance|\bshall\b|EARS)", contents["requirements"]
    ):
        gaps.append("requirements.md has no recognizable acceptance criteria")
    if contents.get("design") and not re.search(
        r"(?im)^#{1,6}\s+.*(design|architecture|interaction|contract)",
        contents["design"],
    ):
        gaps.append("design.md has no recognizable design or contract section")
    if contents.get("tasks") and not re.search(
        r"(?m)^\s*(?:[-*]\s+\[[ xX]\]|\d+[.)]\s+)", contents["tasks"]
    ):
        gaps.append("tasks.md has no recognizable task list")
    return gaps


def handle_spec_readiness(
    event: dict[str, Any], settings: Settings, store: StateStore, phase: str
) -> int:
    """Fail closed for task start and protected implementation actions."""
    if phase == "tool":
        operation = classify_operation(event, settings, load_policy(settings))
        if not operation["protected"]:
            print("AIDE spec-readiness: action is not protected implementation")
            return 0
        workflow = store.load("workflow.json", {})
        if _is_authoring_operation(operation, workflow):
            print("AIDE spec-readiness: active authoring target is pre-implementation")
            return 0
    gaps = spec_readiness(store.load("workflow.json", {}), settings)
    if gaps:
        print("AIDE spec-readiness blocked: " + "; ".join(gaps))
        return 2
    print("AIDE spec-readiness: structure and explicit review are current")
    return 0


def _story_fields(text: str) -> dict[str, str]:
    """Parse the small YAML-like frontmatter contract used by Jira stories."""
    match = re.match(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip().strip("'\"")
    return fields


def _story_gaps(path: Path, expected_key: str) -> tuple[list[str], str]:
    """Return readiness gaps and the full content hash for one story."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"story cannot be read: {error}"], ""
    story_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    fields = _story_fields(text)
    gaps: list[str] = []
    if fields.get("jira_key") != expected_key:
        gaps.append("frontmatter jira_key does not match the filename")
    if fields.get("aide_stage") != "ears-ready":
        gaps.append("frontmatter aide_stage is not ears-ready")
    required_headings = (
        "user story",
        "ears functional requirements",
        "acceptance criteria",
        "traceability",
    )
    for heading in required_headings:
        if not re.search(rf"(?im)^#{{2,6}}\s+.*{re.escape(heading)}", text):
            gaps.append(f"missing {heading} heading")
    if not re.search(r"(?is)\bAs an?\b.+\bI want\b.+\bso that\b", text):
        gaps.append("missing As a / I want / so that statement")
    if not re.search(r"(?im)^.*\b(?:THE SYSTEM|it) SHALL\b", text):
        gaps.append("no EARS SHALL requirement was found")
    return gaps, story_hash


def _spec_document_gaps(spec_dir: Path) -> list[str]:
    """Return structural gaps for the generated specification set."""
    expected = {
        "requirements.md": r"(?i)(acceptance|\bshall\b|EARS)",
        "design.md": r"(?im)^#{1,6}\s+.*(design|architecture|interaction|contract)",
        "tasks.md": r"(?m)^\s*(?:[-*]\s+\[[ xX]\]|\d+[.)]\s+)",
    }
    gaps: list[str] = []
    for name, pattern in expected.items():
        path = spec_dir / name
        if not path.is_file() or path.stat().st_size < 50:
            gaps.append(f"{name} is absent or too small")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(pattern, text):
            gaps.append(f"{name} is missing its required structure")
    return gaps


def initialize_story_intake(
    args: argparse.Namespace, settings: Settings, store: StateStore
) -> int:
    """Initialize one Jira-to-spec lifecycle before the story file is written."""
    jira_key = args.jira_key.strip().upper()
    if not JIRA_KEY.fullmatch(jira_key):
        raise ValueError("jira key must be uppercase and end in a numeric issue id")
    valid, story_path = inside_workspace(settings, args.story_path)
    match = JIRA_STORY.fullmatch(story_path) if valid else None
    if not match or match.group("key") != jira_key:
        raise ValueError(
            "story path must be jira/<JIRA-KEY>-<lowercase-capability-slug>.md"
        )
    spec_name = match.group("slug")
    spec_dir = f".kiro/specs/{spec_name}"
    workflow = {
        "authoring_targets": [f"file:{story_path}"],
        "baseline_revision": git(settings, "rev-parse", "HEAD"),
        "blockers": [],
        "change_class": "normal",
        "created_at": now(),
        "jira_key": jira_key,
        "next_approved_action": "complete EARS story refinement",
        "pending_approval": False,
        "pending_decisions": [],
        "phase": "jira-intake",
        "plan_revision": args.plan_revision,
        "planned_targets": [f"file:{story_path}", f"file:{spec_dir}/**"],
        "required_gate": "spec-readiness",
        "scope_hash": digest(spec_name),
        "scope_id": spec_name,
        "spec_dir": spec_dir,
        "spec_reviewed": False,
        "status": "pending",
        "story_path": story_path,
        "task_id": jira_key,
        "updated_at": now(),
        "verification": "not_run",
    }
    store.save("workflow.json", workflow)
    store.save("approvals.json", {})
    store.save(
        "spec-request.json",
        {
            "attempts": 0,
            "jira_key": jira_key,
            "spec_dir": spec_dir,
            "status": "waiting-for-ears",
            "story_path": story_path,
            "updated_at": now(),
        },
    )
    print(
        json.dumps(
            {
                "action": "author-story",
                "jira_key": jira_key,
                "spec_dir": spec_dir,
                "story_path": story_path,
            },
            sort_keys=True,
        )
    )
    return 0


def handle_story_ready(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Validate an EARS story and queue one idempotent specification request."""
    workflow = store.load("workflow.json", {})
    candidates: list[tuple[str, re.Match[str]]] = []
    for raw_path in extract_paths(event):
        valid, relative = inside_workspace(settings, raw_path)
        match = JIRA_STORY.fullmatch(relative) if valid else None
        if match:
            candidates.append((relative, match))
    if not candidates:
        print(
            json.dumps(
                {"action": "none", "reason": "event has no Jira story path"},
                sort_keys=True,
            )
        )
        return 0

    story_path, match = candidates[0]
    gaps: list[str] = []
    if not workflow:
        gaps.append("Jira intake workflow is not initialized")
    elif workflow.get("story_path") != story_path:
        gaps.append("saved story does not match the active Jira intake")
    path = settings.workspace_root / story_path
    content_gaps, story_hash = _story_gaps(path, match.group("key"))
    gaps.extend(content_gaps)
    result = {
        "action": "none" if gaps else "queue-specification",
        "gaps": gaps,
        "jira_key": match.group("key"),
        "story_hash": story_hash,
        "story_path": story_path,
        "timestamp": now(),
    }
    store.save("story-readiness.json", result)
    if gaps:
        store.save(
            "spec-request.json",
            {
                "attempts": 0,
                "gaps": gaps,
                "jira_key": match.group("key"),
                "status": "waiting-for-ears",
                "story_hash": story_hash,
                "story_path": story_path,
                "updated_at": now(),
            },
        )
        print(json.dumps(result, sort_keys=True))
        return 0

    existing = store.load("spec-request.json", {})
    if existing.get("story_hash") == story_hash:
        request = existing
    else:
        request = {
            "attempts": 0,
            "jira_key": match.group("key"),
            "spec_dir": workflow["spec_dir"],
            "status": "pending",
            "story_hash": story_hash,
            "story_path": story_path,
        }
    request["updated_at"] = now()
    store.save("spec-request.json", request)
    workflow.update(
        {
            "authoring_targets": [
                f"file:{story_path}",
                f"file:{workflow['spec_dir']}/**",
            ],
            "next_approved_action": "generate draft specification",
            "phase": "story-ready",
            "updated_at": now(),
        }
    )
    store.save("workflow.json", workflow)
    print(json.dumps(result, sort_keys=True))
    return 0


def handle_story_to_spec(settings: Settings, store: StateStore) -> int:
    """Return the next bounded specification action for the ready story."""
    request = store.load("spec-request.json", {})
    if request.get("status") == "waiting-for-ears":
        workflow = store.load("workflow.json", {})
        story_path = str(workflow.get("story_path", ""))
        if story_path:
            handle_story_ready(
                {"tool_name": "write", "tool_input": {"path": story_path}},
                settings,
                store,
            )
            request = store.load("spec-request.json", {})
    if request.get("status") in {None, "waiting-for-ears", "complete", "blocked"}:
        print(
            json.dumps(
                {
                    "action": "none",
                    "reason": request.get("status", "no specification request"),
                },
                sort_keys=True,
            )
        )
        return 0

    story_path = str(request.get("story_path", ""))
    valid, relative = inside_workspace(settings, story_path)
    match = JIRA_STORY.fullmatch(relative) if valid else None
    if not match:
        request.update({"status": "blocked", "updated_at": now()})
        store.save("spec-request.json", request)
        print(json.dumps({"action": "blocked", "reason": "invalid story path"}))
        return 0
    gaps, current_hash = _story_gaps(
        settings.workspace_root / relative, match.group("key")
    )
    if gaps or current_hash != request.get("story_hash"):
        request.update(
            {
                "gaps": gaps or ["story changed after readiness validation"],
                "status": "waiting-for-ears",
                "updated_at": now(),
            }
        )
        store.save("spec-request.json", request)
        print(
            json.dumps(
                {"action": "none", "reason": "story readiness is stale"},
                sort_keys=True,
            )
        )
        return 0

    spec_dir = settings.workspace_root / str(request["spec_dir"])
    if request.get("status") == "started":
        spec_gaps = _spec_document_gaps(spec_dir)
        if not spec_gaps:
            request.update({"status": "complete", "updated_at": now()})
            store.save("spec-request.json", request)
            workflow = store.load("workflow.json", {})
            workflow.update(
                {
                    "next_approved_action": "review draft specification",
                    "pending_approval": True,
                    "phase": "spec-review",
                    "required_gate": "spec-readiness",
                    "updated_at": now(),
                }
            )
            store.save("workflow.json", workflow)
            print(
                json.dumps(
                    {
                        "action": "complete",
                        "spec_dir": request["spec_dir"],
                        "story_path": relative,
                    },
                    sort_keys=True,
                )
            )
            return 0
        request["gaps"] = spec_gaps

    attempts = int(request.get("attempts", 0))
    if attempts >= MAX_SPEC_ATTEMPTS:
        request.update({"status": "blocked", "updated_at": now()})
        store.save("spec-request.json", request)
        workflow = store.load("workflow.json", {})
        workflow.update(
            {
                "blockers": request.get("gaps", ["specification generation failed"]),
                "next_approved_action": "review incomplete specification",
                "phase": "blocked",
                "updated_at": now(),
            }
        )
        store.save("workflow.json", workflow)
        print(
            json.dumps(
                {
                    "action": "blocked",
                    "attempts": attempts,
                    "gaps": request.get("gaps", []),
                },
                sort_keys=True,
            )
        )
        return 0

    attempts += 1
    action = "generate" if attempts == 1 else "repair"
    request.update({"attempts": attempts, "status": "started", "updated_at": now()})
    store.save("spec-request.json", request)
    workflow = store.load("workflow.json", {})
    workflow.update(
        {
            "authoring_targets": [f"file:{request['spec_dir']}/**"],
            "next_approved_action": f"{action} draft specification",
            "phase": "spec-authoring",
            "updated_at": now(),
        }
    )
    store.save("workflow.json", workflow)
    print(
        json.dumps(
            {
                "action": action,
                "attempt": attempts,
                "gaps": request.get("gaps", []),
                "jira_key": request["jira_key"],
                "spec_dir": request["spec_dir"],
                "story_path": relative,
            },
            sort_keys=True,
        )
    )
    return 0


def _validate_json(path: Path) -> tuple[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return "failed", str(error)
    if "postman" in path.name.lower():
        if not isinstance(value, dict) or "info" not in value or "item" not in value:
            return "failed", "Postman collection requires top-level info and item"
    return "passed", "JSON parsed without a live request"


def _validate_python(path: Path) -> tuple[str, str]:
    try:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
    except (OSError, SyntaxError) as error:
        return "failed", str(error)
    return "passed", "Python syntax compiled in memory"


def handle_validate_change(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Select and run only local, policy-approved quick checks."""
    paths = extract_paths(event)
    checks: list[dict[str, str]] = []
    for raw_path in paths:
        valid, relative = inside_workspace(settings, raw_path)
        path = settings.workspace_root / relative if valid else Path(raw_path)
        if not valid or not path.is_file():
            checks.append(
                {"path": raw_path, "status": "unknown", "detail": "not a file"}
            )
            continue
        suffix = path.suffix.lower()
        if suffix == ".py":
            status, detail = _validate_python(path)
        elif suffix == ".json":
            status, detail = _validate_json(path)
        elif suffix in {".sh", ".bash"}:
            status, detail = "not_run", "configure an approved Bash syntax command"
        elif suffix in {".yaml", ".yml"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"(?i)\b(kind|hosts|tasks|apiVersion)\s*:", text):
                status, detail = "not_run", "selected YAML; configure an offline linter"
            else:
                status, detail = "unknown", "YAML repository type was not identifiable"
        else:
            status, detail = "not_run", "no approved quick check for this artifact type"
        checks.append({"detail": detail[:500], "path": relative, "status": status})
    statuses = {item["status"] for item in checks}
    overall = (
        "failed"
        if "failed" in statuses
        else "passed"
        if checks and statuses == {"passed"}
        else "not_run"
    )
    record = {
        "changed_artifacts": paths,
        "checks": checks,
        "hook": "aide-validate-change",
        "revision": git(settings, "rev-parse", "HEAD"),
        "status": overall,
        "timestamp": now(),
    }
    store.append("evidence.jsonl", record)
    print(json.dumps(redact(record), sort_keys=True))
    return 1 if overall == "failed" else 0


def handle_task_evidence(
    event: dict[str, Any], settings: Settings, store: StateStore, phase: str
) -> int:
    """Capture tool evidence or summarize new task evidence."""
    if phase == "capture":
        record = event_record("aide-task-evidence", event, settings)
        store.append("evidence.jsonl", record)
        print(json.dumps(record, sort_keys=True))
        return 0
    checkpoint = store.load("evidence-checkpoint.json", {})
    since = checkpoint.get("timestamp", "")
    records = [
        record
        for record in store.tail("evidence.jsonl", 200)
        if record.get("timestamp", "") > since
    ]
    summary = {
        "artifacts": sorted(
            {path for record in records for path in record.get("changed_artifacts", [])}
        )[:100],
        "counts": {
            status: sum(record.get("status") == status for record in records)
            for status in ("passed", "failed", "not_run", "unknown")
        },
        "delegated": any(record.get("delegated") for record in records),
        "phase": phase,
        "record_count": len(records),
        "revision": git(settings, "rev-parse", "HEAD"),
        "timestamp": now(),
    }
    if records:
        store.save("evidence-summary.json", summary)
        store.save("evidence-checkpoint.json", {"timestamp": summary["timestamp"]})
    print(json.dumps(summary, sort_keys=True))
    return 0


def handle_knowledge_drift(settings: Settings, store: StateStore) -> int:
    """Identify narrow documentation candidates from recorded changed artifacts."""
    checkpoint = store.load("knowledge-checkpoint.json", {})
    since = checkpoint.get("timestamp", "")
    records = [
        record
        for record in store.tail("evidence.jsonl", 300)
        if record.get("timestamp", "") > since
    ]
    paths = sorted(
        {
            path
            for record in records
            for path in record.get("changed_artifacts", [])
            if isinstance(path, str)
        }
    )
    candidates: set[str] = set()
    for path in paths:
        lower = path.lower()
        parent = Path(path).parent.as_posix()
        if lower.endswith((".py", ".rs", ".c", ".cc", ".cpp", ".h", ".cu")):
            candidates.update(
                {f"{parent}/SPECS.md", "knowledge-base/LLD.md", "openwiki (secondary)"}
            )
        if lower.endswith((".yaml", ".yml", ".json", ".toml", ".ini")):
            candidates.update({f"{parent}/SPECS.md", "knowledge-base/HLD.md"})
        if "postman" in lower or "openapi" in lower:
            candidates.add("API collections and interface documentation")
        if any(
            marker in lower
            for marker in ("openapi", "asyncapi", ".proto", "/events/", "contract")
        ):
            candidates.add("knowledge-base/knowledge-plane.json")
        if "runbook" in lower or "/ops/" in lower:
            candidates.add("affected runbooks")
    result = {
        "candidate_updates": sorted(candidates),
        "changed_artifacts": paths[:100],
        "has_relevant_change": bool(candidates),
        "instruction": (
            "Propose narrow updates for human review; do not publish and do not write "
            "to Graphiti directly."
        ),
        "timestamp": now(),
    }
    store.save("knowledge-drift.json", result)
    store.save("knowledge-checkpoint.json", {"timestamp": result["timestamp"]})
    print(json.dumps(result, sort_keys=True))
    return 0


def handle_session_context(settings: Settings, store: StateStore) -> int:
    """Load a minimal resume context without authorizing execution."""
    workflow = store.load("workflow.json", {})
    approvals = store.load("approvals.json", {})
    summary = store.load("evidence-summary.json", {})
    status_lines = git(settings, "status", "--short").splitlines()[:25]
    context = {
        "active_task": workflow.get("task_id", "uninitialized"),
        "approved_gates": sorted(
            gate
            for gate, item in approvals.items()
            if isinstance(item, dict) and item.get("decision") == "approve"
        )
        if isinstance(approvals, dict)
        else [],
        "branch": git(settings, "branch", "--show-current"),
        "latest_evidence": summary,
        "pending_decisions": workflow.get("pending_decisions", []),
        "plan_revision": workflow.get("plan_revision", "unknown"),
        "scope_id": workflow.get("scope_id", "unknown"),
        "working_tree_changes": status_lines,
    }
    print("AIDE resume context only; this does not authorize execution.\n")
    print(json.dumps(redact(context), indent=2, sort_keys=True))
    return 0


def _prompt_text(event: dict[str, Any]) -> str:
    explicit = os.environ.get("AIDE_USER_PROMPT") or os.environ.get("USER_PROMPT")
    if explicit:
        return explicit
    value = find_value(event, {"userprompt", "prompt", "message", "text"})
    return str(value or "")


def parse_decision(prompt: str) -> dict[str, Any] | None:
    """Parse only an explicit, standalone AIDE decision declaration."""
    first_line = prompt.strip().splitlines()[0] if prompt.strip() else ""
    if not first_line.lower().startswith("aide-decision "):
        return None
    try:
        tokens = shlex.split(first_line)
    except ValueError:
        return {"error": "decision declaration has invalid quoting"}
    if len(tokens) < 2 or tokens[1].lower() not in {"approve", "reject", "revise"}:
        return {"error": "decision must be approve, reject, or revise"}
    fields: dict[str, str] = {}
    for token in tokens[2:]:
        if "=" not in token:
            return {"error": f"decision field is not key=value: {token}"}
        key, value = token.split("=", 1)
        fields[key.lower()] = value
    required = {"task", "gate", "revision", "scope"}
    if tokens[1].lower() == "approve":
        required.add("targets")
    missing = sorted(required - fields.keys())
    if missing:
        return {"error": "missing fields: " + ", ".join(missing)}
    targets = [
        item.strip() for item in fields.get("targets", "").split(",") if item.strip()
    ]
    return {
        "decision": tokens[1].lower(),
        "gate": fields["gate"],
        "plan_revision": fields["revision"],
        "scope_hash": digest(fields["scope"]),
        "scope_id": fields["scope"],
        "targets": targets,
        "task_id": fields["task"],
    }


def handle_human_decision(
    event: dict[str, Any], settings: Settings, store: StateStore
) -> int:
    """Record explicit approval events without storing the user's conversation."""
    prompt = _prompt_text(event)
    parsed = parse_decision(prompt)
    if parsed is None:
        store.append(
            "human-events.jsonl",
            {
                "explicit_decision": False,
                "prompt_hash": digest(prompt),
                "timestamp": now(),
            },
        )
        print("AIDE decision: no explicit approval event; approval state unchanged")
        return 0
    if "error" in parsed:
        print(f"AIDE decision ignored: {parsed['error']}")
        return 0
    workflow = store.load("workflow.json", {})
    matches = all(
        workflow.get(key) == parsed.get(key)
        for key in ("task_id", "plan_revision", "scope_hash")
    )
    record = {
        **parsed,
        "prompt_hash": digest(prompt),
        "recorded_at": now(),
        "workflow_match": matches,
    }
    store.append("human-events.jsonl", record)
    approvals = store.load("approvals.json", {})
    if not isinstance(approvals, dict):
        approvals = {}
    gate = parsed["gate"]
    if parsed["decision"] == "approve" and matches:
        approvals[gate] = record
        if gate == "spec-readiness":
            workflow["spec_reviewed"] = True
            workflow["required_gate"] = "implementation"
            if workflow.get("change_class") == "small":
                workflow["lightweight_approved"] = True
            workflow["updated_at"] = now()
            store.save("workflow.json", workflow)
        message = f"recorded current explicit approval for gate {gate}"
    elif parsed["decision"] == "revise":
        approvals = {}
        workflow.update(
            {
                "plan_revision": parsed["plan_revision"],
                "scope_hash": parsed["scope_hash"],
                "scope_id": parsed["scope_id"],
                "required_gate": "spec-readiness",
                "spec_reviewed": False,
                "updated_at": now(),
            }
        )
        store.save("workflow.json", workflow)
        message = "revision recorded and prior approvals invalidated"
    else:
        approvals.pop(gate, None)
        message = (
            "approval not recorded because state does not match"
            if parsed["decision"] == "approve"
            else f"gate {gate} rejected and invalidated"
        )
    store.save("approvals.json", approvals)
    print("AIDE decision: " + message)
    handle_checkpoint(settings, store, "decision")
    return 0


def handle_checkpoint(settings: Settings, store: StateStore, phase: str) -> int:
    """Derive workflow status from evidence without claiming task completion."""
    workflow = store.load("workflow.json", {})
    if not workflow:
        print("AIDE checkpoint: workflow is uninitialized; no state was advanced")
        return 0
    previous = store.load("workflow-checkpoint.json", {})
    since = previous.get("timestamp", "")
    records = [
        record
        for record in store.tail("evidence.jsonl", 300)
        if record.get("timestamp", "") > since
    ]
    statuses = [record.get("status", "unknown") for record in records]
    if "failed" in statuses:
        verification = "failed"
    elif statuses and all(status == "passed" for status in statuses):
        verification = "passed"
    elif "not_run" in statuses:
        verification = "not_run"
    else:
        verification = "unknown"
    approvals = store.load("approvals.json", {})
    required_gate = workflow.get("required_gate") or (
        "implementation" if workflow.get("spec_reviewed") else "spec-readiness"
    )
    required_approval = (
        approvals.get(required_gate, {}) if isinstance(approvals, dict) else {}
    )
    current_approval = (
        isinstance(required_approval, dict)
        and required_approval.get("decision") == "approve"
        and required_approval.get("task_id") == workflow.get("task_id")
        and required_approval.get("plan_revision") == workflow.get("plan_revision")
        and required_approval.get("scope_hash") == workflow.get("scope_hash")
    )
    workflow.update(
        {
            "branch": git(settings, "branch", "--show-current"),
            "checkpoint_phase": phase,
            "pending_approval": not current_approval,
            "required_gate": required_gate,
            "revision": git(settings, "rev-parse", "HEAD"),
            "updated_at": now(),
            "verification": verification,
        }
    )
    if not current_approval:
        workflow["next_approved_action"] = "obtain explicit approval"
    elif verification == "failed":
        workflow["next_approved_action"] = "review failed verification evidence"
    store.save("workflow.json", workflow)
    checkpoint = {
        "evidence_records": len(records),
        "phase": phase,
        "status": "pending",
        "timestamp": now(),
        "verification": verification,
    }
    store.save("workflow-checkpoint.json", checkpoint)
    print(json.dumps(checkpoint, sort_keys=True))
    return 0


def initialize_workflow(
    args: argparse.Namespace, settings: Settings, store: StateStore
) -> int:
    """Initialize a task-scoped workflow and invalidate earlier approvals."""
    spec_dir = args.spec_dir or ""
    lightweight_spec = args.lightweight_spec or ""
    workflow = {
        "blockers": [],
        "change_class": args.change_class,
        "created_at": now(),
        "lightweight_approved": False,
        "lightweight_spec": lightweight_spec,
        "next_approved_action": "review specification readiness",
        "pending_approval": True,
        "pending_decisions": [],
        "plan_revision": args.plan_revision,
        "planned_targets": args.target,
        "required_gate": "spec-readiness",
        "scope_hash": digest(args.scope),
        "scope_id": args.scope,
        "spec_dir": spec_dir,
        "spec_reviewed": False,
        "status": "pending",
        "task_id": args.task,
        "updated_at": now(),
        "verification": "not_run",
    }
    store.save("workflow.json", workflow)
    store.save("approvals.json", {})
    print(
        f"Initialized AIDE workflow {args.task} at revision {args.plan_revision}; "
        "all approvals are pending."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(prog="aide-hook")
    subparsers = parser.add_subparsers(dest="hook", required=True)
    for name in (
        "aide-validate-change",
        "aide-safe-operation",
        "aide-session-context",
        "aide-record-human-decision",
        "aide-approval-gate",
        "aide-knowledge-drift",
        "aide-story-ready",
        "aide-story-to-spec",
        "aide-azure-read-only",
        "aide-azure-observation-evidence",
        "aide-azure-change-control",
        "aide-azure-change-evidence",
        "aide-kubernetes-read-only",
        "aide-kubernetes-observation-evidence",
        "aide-kubernetes-change-control",
        "aide-kubernetes-change-evidence",
    ):
        subparsers.add_parser(name)
    evidence = subparsers.add_parser("aide-task-evidence")
    evidence.add_argument(
        "--phase", choices=("capture", "post-task", "stop"), default="capture"
    )
    readiness = subparsers.add_parser("aide-spec-readiness")
    readiness.add_argument("--phase", choices=("task", "tool"), default="task")
    checkpoint = subparsers.add_parser("aide-workflow-checkpoint")
    checkpoint.add_argument(
        "--phase", choices=("decision", "post-task", "stop"), default="stop"
    )
    initialize = subparsers.add_parser("init")
    initialize.add_argument("--task", required=True)
    initialize.add_argument("--plan-revision", required=True)
    initialize.add_argument("--scope", required=True)
    initialize.add_argument("--target", action="append", default=[])
    initialize.add_argument("--spec-dir")
    initialize.add_argument(
        "--change-class", choices=("normal", "small"), default="normal"
    )
    initialize.add_argument("--lightweight-spec")
    story = subparsers.add_parser("init-story")
    story.add_argument("--jira-key", required=True)
    story.add_argument("--story-path", required=True)
    story.add_argument("--plan-revision", default="r1")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch one Kiro hook event."""
    args = build_parser().parse_args(argv)
    settings = Settings.load()
    store = StateStore(settings)
    if args.hook == "init":
        return initialize_workflow(args, settings, store)
    if args.hook == "init-story":
        return initialize_story_intake(args, settings, store)
    event = read_event()
    handlers = {
        "aide-validate-change": lambda: handle_validate_change(event, settings, store),
        "aide-safe-operation": lambda: handle_safe_operation(event, settings, store),
        "aide-task-evidence": lambda: handle_task_evidence(
            event, settings, store, args.phase
        ),
        "aide-spec-readiness": lambda: handle_spec_readiness(
            event, settings, store, args.phase
        ),
        "aide-knowledge-drift": lambda: handle_knowledge_drift(settings, store),
        "aide-session-context": lambda: handle_session_context(settings, store),
        "aide-record-human-decision": lambda: handle_human_decision(
            event, settings, store
        ),
        "aide-approval-gate": lambda: handle_approval_gate(event, settings, store),
        "aide-story-ready": lambda: handle_story_ready(event, settings, store),
        "aide-story-to-spec": lambda: handle_story_to_spec(settings, store),
        "aide-azure-read-only": lambda: handle_azure_read_only(event, settings, store),
        "aide-azure-observation-evidence": lambda: handle_azure_observation(
            event, settings, store
        ),
        "aide-azure-change-control": lambda: handle_azure_change_control(
            event, settings, store
        ),
        "aide-azure-change-evidence": lambda: handle_azure_change_evidence(
            event, settings, store
        ),
        "aide-kubernetes-read-only": lambda: handle_kubernetes_read_only(
            event, settings, store
        ),
        "aide-kubernetes-observation-evidence": lambda: handle_kubernetes_observation(
            event, settings, store
        ),
        "aide-kubernetes-change-control": lambda: handle_kubernetes_change_control(
            event, settings, store
        ),
        "aide-kubernetes-change-evidence": lambda: handle_kubernetes_change_evidence(
            event, settings, store
        ),
        "aide-workflow-checkpoint": lambda: handle_checkpoint(
            settings, store, args.phase
        ),
    }
    return handlers[args.hook]()


if __name__ == "__main__":
    raise SystemExit(main())
