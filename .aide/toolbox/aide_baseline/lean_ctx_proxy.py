"""Expose LeanCTX's read-only context tools to Kiro over MCP stdio."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import Any

ALLOWED_TOOLS = frozenset({"ctx_read", "ctx_search", "ctx_glob", "ctx_tree"})
ALLOWED_REQUESTS = frozenset({"initialize", "ping", "tools/list", "tools/call"})
ALLOWED_NOTIFICATIONS = frozenset(
    {"notifications/initialized", "notifications/cancelled"}
)


def _send(message: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def _error(request_id: Any, lock: threading.Lock) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "MCP tool is not available"},
        },
        lock,
    )


def _allowed_call(params: Any) -> bool:
    return isinstance(params, dict) and params.get("name") in ALLOWED_TOOLS


def _relay_responses(
    child: subprocess.Popen[str],
    pending: dict[Any, str],
    lock: threading.Lock,
) -> None:
    assert child.stdout is not None
    for line in child.stdout:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict) or "id" not in message:
            continue
        with lock:
            method = pending.pop(message["id"], None)
        if method is None:
            continue
        if method == "tools/list":
            result = message.get("result")
            if isinstance(result, dict):
                tools = result.get("tools")
                if isinstance(tools, list):
                    result["tools"] = [
                        tool
                        for tool in tools
                        if isinstance(tool, dict)
                        and tool.get("name") in ALLOWED_TOOLS
                    ]
        _send(message, lock)


def serve(binary: str) -> int:
    """Relay only approved MCP methods and read-only tool calls."""

    child = subprocess.Popen(
        [binary],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert child.stdin is not None
    pending: dict[Any, str] = {}
    lock = threading.Lock()
    reader = threading.Thread(
        target=_relay_responses, args=(child, pending, lock), daemon=True
    )
    reader.start()
    try:
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            method = message.get("method")
            if not isinstance(method, str):
                continue
            request_id = message.get("id")
            if "id" not in message:
                if method in ALLOWED_NOTIFICATIONS:
                    child.stdin.write(line)
                    child.stdin.flush()
                continue
            if method not in ALLOWED_REQUESTS:
                _error(request_id, lock)
                continue
            if method == "tools/call":
                if not _allowed_call(message.get("params")):
                    _error(request_id, lock)
                    continue
            with lock:
                pending[request_id] = method
            child.stdin.write(line)
            child.stdin.flush()
    finally:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        reader.join(timeout=3)
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("Expected the workspace-local LeanCTX binary path", file=sys.stderr)
        return 2
    return serve(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
