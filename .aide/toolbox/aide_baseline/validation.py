"""Validation contracts and deterministic command execution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .util import command_exists, safe_join, utc_now

TERMINAL = {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_CONFIGURED"}


def validate_contract(contract: dict[str, Any]) -> None:
    """Reject shell strings and incomplete validation contracts."""

    if not isinstance(contract.get("executable"), str):
        raise ConfigurationError("Validation executable must be a string.")
    if not isinstance(contract.get("args", []), list) or not all(
        isinstance(value, str) for value in contract.get("args", [])
    ):
        raise ConfigurationError("Validation args must be a string list.")
    timeout = contract.get("timeout_seconds", 120)
    if not isinstance(timeout, int) or timeout <= 0 or timeout > 3600:
        raise ConfigurationError(
            "Validation timeout must be between 1 and 3600 seconds."
        )
    if "expected_evidence" not in contract:
        raise ConfigurationError("Validation expected_evidence must be explicit.")


def run_validations(
    root: Path, contracts: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Execute only explicitly configured executable-plus-argument contracts."""

    if not contracts:
        return {
            "status": "NOT_CONFIGURED",
            "checks": [],
            "message": "No validation commands are configured; this is not a pass.",
        }
    results: list[dict[str, Any]] = []
    for index, contract in enumerate(contracts, 1):
        validate_contract(contract)
        executable = contract["executable"]
        name = contract.get("name", f"validation-{index}")
        required = bool(contract.get("required", True))
        working = contract.get("working_directory", ".")
        if working in {"", "."}:
            cwd = root
        else:
            cwd = safe_join(root, working, allow_leaf_missing=False)
            if not cwd.is_dir():
                raise ConfigurationError(
                    f"Validation working directory is not a directory: {working}"
                )
        if not command_exists(executable):
            results.append(
                {
                    "name": name,
                    "status": "BLOCKED" if required else "NOT_RUN",
                    "reason": f"Executable not found: {executable}",
                    "required": required,
                }
            )
            continue
        started = utc_now()
        try:
            completed = subprocess.run(
                [executable, *contract.get("args", [])],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=contract.get("timeout_seconds", 120),
                shell=False,
            )
            status = "PASS" if completed.returncode == 0 else "FAIL"
            results.append(
                {
                    "name": name,
                    "status": status,
                    "required": required,
                    "started_at": started,
                    "finished_at": utc_now(),
                    "exit_code": completed.returncode,
                    "command": [executable, *contract.get("args", [])],
                    "working_directory": working,
                    "expected_evidence": contract["expected_evidence"],
                    "stdout": completed.stdout[-20000:],
                    "stderr": completed.stderr[-20000:],
                }
            )
        except subprocess.TimeoutExpired as exc:
            results.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "required": required,
                    "reason": (
                        f"Timed out after {contract.get('timeout_seconds', 120)} "
                        "seconds"
                    ),
                    "stdout": (exc.stdout or "")[-20000:],
                    "stderr": (exc.stderr or "")[-20000:],
                }
            )
    required_results = [item for item in results if item["required"]]
    if not required_results:
        overall = "NOT_CONFIGURED"
    elif any(item["status"] == "FAIL" for item in required_results):
        overall = "FAIL"
    elif any(item["status"] == "BLOCKED" for item in required_results):
        overall = "BLOCKED"
    elif required_results and all(
        item["status"] == "PASS" for item in required_results
    ):
        overall = "PASS"
    else:
        overall = "NOT_RUN"
    return {"status": overall, "checks": results}
