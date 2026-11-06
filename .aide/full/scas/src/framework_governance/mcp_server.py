from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from .jobs import JobManager
from .service import GovernanceService

PROTOCOL_VERSION = "2025-06-18"


TOOLS = [
    {
        "name": "scan_repository",
        "description": (
            "Scan a repository and return deterministic framework, library, "
            "runtime and base-image inventory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository_path": {"type": "string", "default": "."},
                "config_path": {"type": ["string", "null"]},
            },
            "required": ["repository_path"],
        },
    },
    {
        "name": "run_assessment",
        "description": (
            "Start a durable background assessment. Returns immediately with "
            "inventory projection, job ID, item count and initial ETA."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository_path": {"type": "string", "default": "."},
                "config_path": {"type": "string"},
                "output_directory": {"type": "string", "default": "reports"},
            },
            "required": ["repository_path", "config_path", "output_directory"],
        },
    },
    {
        "name": "start_assessment_job",
        "description": (
            "Start a durable background SCAS assessment and return its initial "
            "inventory, projected duration and job ID."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository_path": {"type": "string", "default": "."},
                "config_path": {"type": "string"},
                "output_directory": {"type": "string", "default": "reports"},
            },
            "required": ["repository_path", "config_path", "output_directory"],
        },
    },
    {
        "name": "get_assessment_status",
        "description": (
            "Get current percentage, completed/remaining counts, current "
            "item/status, elapsed time, live ETA, heartbeat and result counts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "include_projection": {"type": "boolean", "default": False},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "wait_for_assessment_update",
        "description": (
            "Wait up to 25 seconds for the next heartbeat or progress revision, "
            "then return compact live status. Repeat until terminal."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "after_revision": {"type": "integer", "default": 0},
                "timeout_seconds": {"type": "number", "default": 20},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "list_assessment_jobs",
        "description": (
            "List recent durable assessment jobs, including progress and "
            "latest ETA."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        },
    },
    {
        "name": "cancel_assessment_job",
        "description": (
            "Request graceful cancellation of a running assessment job. The "
            "current HTTP request may finish before cancellation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "check_component",
        "description": (
            "Check one named component and version with SCAS Search 3PP using "
            "the configured policy."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "version": {"type": ["string", "null"]},
                "ecosystem": {"type": "string", "default": "unknown"},
                "config_path": {"type": "string"},
            },
            "required": ["name", "config_path"],
        },
    },
    {
        "name": "get_knowledge_document",
        "description": (
            "Read an approved agent knowledge-base document such as HLD, LLD, "
            "SPECS, status policy or SCAS contract."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document": {
                    "type": "string",
                    "enum": [
                        "HLD",
                        "LLD",
                        "SPECS",
                        "SCAS-CONTRACT",
                        "SCSS-CONTRACT",
                        "STATUS-POLICY",
                        "OPERATIONS",
                    ],
                }
            },
            "required": ["document"],
        },
    },
]


class McpServer:
    def __init__(self):
        self.service = GovernanceService()
        self.jobs = JobManager()

    def run(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
                response = self.handle(message)
                if response is not None:
                    self._send(response)
            except Exception as exc:
                self._send({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": str(exc)},
                })

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if request_id is None:
            return None
        if method == "initialize":
            requested = message.get("params", {}).get("protocolVersion")
            return self._result(request_id, {
                "protocolVersion": requested or PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "framework-governance", "version": "0.5.0"},
            })
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(request_id, {"tools": TOOLS})
        if method == "tools/call":
            params = message.get("params", {})
            try:
                output = self._call_tool(
                    params.get("name"), params.get("arguments", {})
                )
                return self._result(request_id, {
                    "content": [{"type": "text", "text": json.dumps(output, indent=2)}],
                    "isError": False,
                })
            except Exception as exc:
                return self._result(request_id, {
                    "content": [
                        {"type": "text", "text": f"{exc}\n{traceback.format_exc()}"}
                    ],
                    "isError": True,
                })
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "scan_repository":
            return self.service.scan(
                arguments.get("repository_path", "."),
                arguments.get("config_path"),
            ).to_dict()
        if name in {"run_assessment", "start_assessment_job"}:
            return self.jobs.start_job(
                arguments.get("repository_path", "."),
                arguments["config_path"],
                arguments.get("output_directory", "reports"),
            )
        if name == "get_assessment_status":
            status = self.jobs.get_status(arguments["job_id"])
            if not arguments.get("include_projection", False):
                status = compact_job_status(status)
            return status
        if name == "wait_for_assessment_update":
            return compact_job_status(
                self.jobs.wait_for_update(
                    arguments["job_id"],
                    int(arguments.get("after_revision", 0)),
                    float(arguments.get("timeout_seconds", 20)),
                )
            )
        if name == "list_assessment_jobs":
            return self.jobs.list_jobs(int(arguments.get("limit", 20)))
        if name == "cancel_assessment_job":
            return compact_job_status(self.jobs.cancel_job(arguments["job_id"]))
        if name == "check_component":
            return self.service.check_component(arguments, arguments["config_path"])
        if name == "get_knowledge_document":
            document = arguments["document"]
            if document == "SCSS-CONTRACT":
                document = "SCAS-CONTRACT"
            if document not in {
                "HLD", "LLD", "SPECS", "SCAS-CONTRACT", "STATUS-POLICY", "OPERATIONS"
            }:
                raise ValueError(f"Unknown knowledge document: {document}")
            default_root = Path(__file__).resolve().parents[2] / "knowledge-base"
            root = Path(os.environ.get("SCAS_KNOWLEDGE_ROOT") or default_root)
            path = root / f"{document}.md"
            if not path.exists():
                raise FileNotFoundError(f"Knowledge document not found: {path}")
            return {"document": document, "content": path.read_text(encoding="utf-8")}
        raise ValueError(f"Unknown tool: {name}")

    @staticmethod
    def _result(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _send(message: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def compact_job_status(state: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "job_id",
        "status",
        "health",
        "health_message",
        "phase",
        "revision",
        "summary",
        "total_items",
        "processed_items",
        "remaining_items",
        "progress_percent",
        "current_item",
        "current_item_status",
        "last_completed_item",
        "recent_items",
        "status_counts",
        "elapsed_seconds",
        "average_item_seconds",
        "eta_seconds",
        "eta_at",
        "heartbeat_at",
        "updated_at",
        "worker_pid",
        "cancel_requested",
        "assessment_summary",
        "reports",
        "error",
        "wait_timed_out",
    ]
    return {key: state.get(key) for key in keys if key in state}


def main() -> None:
    McpServer().run()


if __name__ == "__main__":
    main()
