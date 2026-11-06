"""Integration catalogue rendering and non-mutating readiness checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .util import read_json, redact


def load_catalog(source_root: Path) -> dict[str, dict[str, Any]]:
    """Load all versioned integration descriptors."""

    catalogue: dict[str, dict[str, Any]] = {}
    descriptor_root = source_root / "mcp" / "descriptors"
    if not descriptor_root.exists():
        descriptor_root = source_root / "integrations" / "descriptors"
    for path in sorted(descriptor_root.glob("*.json")):
        value = read_json(path)
        catalogue[value["name"]] = value
    return catalogue


def status(source_root: Path, selected: list[str] | None = None) -> dict[str, Any]:
    """Evaluate local configuration without contacting endpoints."""

    catalogue = load_catalog(source_root)
    names = selected or sorted(catalogue)
    results = []
    for name in names:
        if name not in catalogue:
            raise ConfigurationError(f"Unknown integration: {name}")
        descriptor = catalogue[name]
        missing = [
            ref for ref in descriptor.get("secret_refs", []) if not os.getenv(ref)
        ]
        configured = not missing and not descriptor.get(
            "requires_explicit_configuration", False
        )
        results.append(
            {
                "name": name,
                "status": "DISABLED" if not configured else "CONFIGURED_NOT_CONNECTED",
                "missing_secret_refs": missing,
                "transport": descriptor.get("transport"),
                "upstream": descriptor.get("upstream"),
                "version": descriptor.get("version"),
                "license": descriptor.get("license"),
                "verified_on": descriptor.get("verified_on"),
                "corrective_action": descriptor.get("corrective_action")
                if not configured
                else None,
            }
        )
    return {"integrations": results, "connections_attempted": 0}


def render_mcp_entry(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Render a disabled Kiro entry without embedding secret values."""

    entry = dict(descriptor["kiro_template"])
    entry["disabled"] = True
    return entry


def _resolve_env(value: str) -> str | None:
    if value.startswith("${env:") and value.endswith("}"):
        return os.getenv(value[6:-1])
    if value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1])
    return value


def _messages() -> list[dict[str, Any]]:
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "aide-doctor", "version": "0.16.3"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]


def _response_summary(values: list[dict[str, Any]]) -> dict[str, Any]:
    initialize = next((value for value in values if value.get("id") == 1), None)
    tools = next((value for value in values if value.get("id") == 2), None)
    tool_values = (tools or {}).get("result", {}).get("tools", [])
    names = [item.get("name", "<unnamed>") for item in tool_values]
    if not initialize or "error" in initialize or not tools or "error" in tools:
        return {
            "status": "BLOCKED",
            "reason": "MCP initialize or tools/list response was missing or failed.",
            "response_ids": [value.get("id") for value in values],
        }
    return {
        "status": "HANDSHAKE_TOOL_DISCOVERY_SUCCEEDED",
        "tools_count": len(names),
        "tool_names": names,
        "mutating_tools_invoked": 0,
    }


def handshake_stdio(descriptor: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    """Launch an explicitly configured stdio server for initialize/tools-list only."""

    if descriptor.get("transport") != "stdio":
        return {"status": "NOT_RUN", "reason": "Integration is not stdio."}
    template = descriptor.get("kiro_template", {})
    command = template.get("command")
    if (
        not isinstance(command, str)
        or "must-be-configured" in command
        or shutil.which(command) is None
    ):
        return {"status": "BLOCKED", "reason": "Stdio command is not resolved."}
    environment = os.environ.copy()
    for key, value in template.get("env", {}).items():
        resolved = _resolve_env(value)
        if resolved is None:
            return {
                "status": "BLOCKED",
                "reason": f"Missing environment reference: {key}",
            }
        environment[key] = resolved
    payload = "".join(json.dumps(message) + "\n" for message in _messages())
    try:
        completed = subprocess.run(
            [command, *template.get("args", [])],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=environment,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "BLOCKED", "reason": str(exc)}
    values = []
    for line in completed.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    result = _response_summary(values)
    result["process_exit_code"] = completed.returncode
    return redact(result)


def handshake_http(descriptor: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    """Perform explicit MCP initialize and tools/list probes without mutations."""

    if descriptor.get("transport") not in {"http", "streamable-http"}:
        return {"status": "NOT_RUN", "reason": "Only HTTP handshake is implemented."}
    url = descriptor.get("resolved_url") or descriptor.get("kiro_template", {}).get(
        "url"
    )
    if isinstance(url, str) and url.startswith("${env:") and url.endswith("}"):
        url = os.getenv(url[6:-1])
    if not url:
        return {"status": "BLOCKED", "reason": "Endpoint is not resolved."}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    for key, value in descriptor.get("headers", {}).items():
        headers[key] = value
    messages = _messages()
    observed = []
    session_id: str | None = None
    try:
        for message in messages:
            request_headers = dict(headers)
            if session_id:
                request_headers["Mcp-Session-Id"] = session_id
            request = urllib.request.Request(
                url,
                data=json.dumps(message).encode("utf-8"),
                headers=request_headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id") or session_id
                observed.append(
                    {
                        "method": message["method"],
                        "status_code": response.status,
                        "content_type": response.headers.get("Content-Type"),
                        "session_established": bool(session_id),
                    }
                )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "BLOCKED", "reason": str(exc), "observed": observed}
    return {
        "status": "CONNECTED_TOOL_DISCOVERY_ATTEMPTED",
        "observed": redact(observed),
    }


def handshake(descriptor: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    """Select the descriptor's non-mutating handshake implementation."""

    if descriptor.get("transport") == "stdio":
        return handshake_stdio(descriptor, timeout)
    return handshake_http(descriptor, timeout)
