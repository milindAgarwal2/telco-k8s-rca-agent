"""Logical hook catalogue, Kiro compatibility rendering, and dispatch guards."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import ApprovalError, ConfigurationError
from .util import (
    atomic_write,
    canonical_json,
    read_json,
    safe_join,
    sha256_value,
    utc_now,
)

HOOKS: dict[str, dict[str, Any]] = {
    "aide-validate-change": {
        "trigger": "PostToolUse",
        "matcher": "write|write_file|edit|edit_file|apply_patch|fs_write",
        "mode": "observe",
        "description": (
            "Record changed paths and request the narrowest configured validation."
        ),
    },
    "aide-safe-operation": {
        "trigger": "PreToolUse",
        "matcher": "shell|execute_bash|powershell",
        "mode": "block",
        "description": "Reject unsafe or unapproved operational command execution.",
    },
    "aide-task-evidence": {
        "trigger": "PostToolUse",
        "matcher": "shell|execute_bash|powershell",
        "mode": "observe",
        "description": (
            "Capture command outcome as workflow evidence without converting empty "
            "output to PASS."
        ),
    },
    "aide-spec-readiness": {
        "trigger": "PreTaskExec",
        "matcher": "",
        "mode": "block",
        "description": (
            "Require ready reviewed specifications before protected task execution."
        ),
    },
    "aide-knowledge-drift": {
        "trigger": "PostTaskExec",
        "matcher": "",
        "mode": "observe",
        "description": "Identify knowledge candidates affected by a completed task.",
    },
    "aide-session-context": {
        "trigger": "SessionStart",
        "matcher": "",
        "mode": "context",
        "description": "Load minimal project and workflow context at session start.",
    },
    "aide-record-human-decision": {
        "trigger": "UserPromptSubmit",
        "matcher": "",
        "mode": "observe",
        "description": (
            "Record explicit human decisions without treating ordinary prompts as "
            "approval."
        ),
    },
    "aide-approval-gate": {
        "trigger": "PreToolUse",
        "matcher": (
            "write|write_file|edit|edit_file|apply_patch|fs_write|shell|"
            "execute_bash|powershell"
        ),
        "mode": "block",
        "description": (
            "Block protected actions without a current plan, scope, revision, and "
            "target binding."
        ),
    },
    "aide-workflow-checkpoint": {
        "trigger": "Stop",
        "matcher": "",
        "mode": "observe",
        "description": "Persist the current workflow checkpoint and unresolved gates.",
    },
}


def render_current(name: str, python_command: str = "python") -> bytes:
    """Render a current Kiro v1 standalone hook."""

    if name not in HOOKS:
        raise ConfigurationError(f"Unknown hook: {name}")
    spec = HOOKS[name]
    command = f"{python_command} .aide/toolbox/aide.py hook dispatch --name {name}"
    entry: dict[str, Any] = {
        "name": name,
        "description": spec["description"],
        "trigger": spec["trigger"],
        "action": {"type": "command", "command": command},
        "timeout": 30,
        "enabled": True,
    }
    if spec["matcher"]:
        entry["matcher"] = spec["matcher"]
    return canonical_json({"version": "v1", "hooks": [entry]})


def render_cli2_embedded(
    python_command: str = "python",
    *,
    include_token_saver: bool = False,
    include_names: set[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Render legacy CLI 2.x hooks grouped by supported trigger."""

    trigger_map = {
        "PreToolUse": "preToolUse",
        "PostToolUse": "postToolUse",
        "UserPromptSubmit": "userPromptSubmit",
        "SessionStart": "agentSpawn",
        "Stop": "stop",
    }
    rendered: dict[str, list[dict[str, str]]] = {}
    for name, spec in HOOKS.items():
        if include_names is not None and name not in include_names:
            continue
        trigger = trigger_map.get(spec["trigger"])
        if trigger is None:
            continue
        entry = {
            "command": (
                f"{python_command} .aide/toolbox/aide.py hook dispatch --name {name}"
            )
        }
        if spec["matcher"]:
            entry["matcher"] = spec["matcher"]
        rendered.setdefault(trigger, []).append(entry)
    if include_token_saver:
        command = (
            "uv run --project .aide/full/mcp-servers/aide-token-saver "
            "--offline --frozen --no-sync aide-token-saver hook"
        )
        rendered.setdefault("userPromptSubmit", []).append(
            {"command": f"{command} PromptSubmit --workspace ."}
        )
        rendered.setdefault("postToolUse", []).append(
            {
                "command": f"{command} PostToolUse --workspace .",
                "matcher": ".*",
            }
        )
        rendered.setdefault("stop", []).append(
            {"command": f"{command} Stop --workspace ."}
        )
    return rendered


def dispatch(
    root: Path, name: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Handle a hook once while preventing recursive or duplicate events."""

    if name not in HOOKS:
        raise ConfigurationError(f"Unknown hook: {name}")
    if os.getenv("AIDE_HOOK_ACTIVE") == "1":
        return {"status": "SKIPPED_RECURSION", "hook": name}
    payload = payload or {}
    event_id = str(payload.get("event_id") or sha256_value(payload))
    state_path = safe_join(root, ".aide/local/hook-events.json")
    state = read_json(state_path) if state_path.exists() else {"events": []}
    key = f"{name}:{event_id}"
    if key in state["events"]:
        return {"status": "SKIPPED_DUPLICATE", "hook": name, "event_id": event_id}
    state["events"] = (state["events"] + [key])[-500:]
    atomic_write(state_path, canonical_json(state))
    if (
        HOOKS[name]["mode"] == "block"
        and payload.get("protected")
        and not payload.get("approved")
    ):
        raise ApprovalError(f"{name} blocked an unapproved protected operation.")
    record = {"status": "PASS", "hook": name, "event_id": event_id, "at": utc_now()}
    return record
