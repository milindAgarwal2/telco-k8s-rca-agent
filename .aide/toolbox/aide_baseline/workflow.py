"""Local workflow state, approval receipts, and evidence binding."""

from __future__ import annotations

import fnmatch
import uuid
from pathlib import Path
from typing import Any

from .errors import ApprovalError, ConfigurationError, SafetyError
from .util import (
    atomic_write,
    canonical_json,
    fingerprint_paths,
    git_changed_paths,
    git_revision,
    read_json,
    repository_snapshot,
    safe_join,
    sha256_value,
    utc_now,
)

STATES = {
    "NEW",
    "CONTEXT_READY",
    "SPEC_READY",
    "AWAITING_APPROVAL",
    "APPROVED",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEW_PENDING",
    "AWAITING_ACCEPTANCE",
    "COMPLETED",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "OUTCOME_UNKNOWN",
}
PROTECTED = (
    ".aide/baseline.lock.json",
    ".aide/managed-files.json",
    ".aide/hooks/**",
    ".kiro/hooks/**",
    ".kiro/agents/**",
    ".kiro/settings/mcp.json",
)


def runs_dir(root: Path) -> Path:
    """Return the ignored local workflow directory."""

    return safe_join(root, ".aide/local/runs")


def _run_path(root: Path, run_id: str) -> Path:
    if not run_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for char in run_id
    ):
        raise SafetyError(f"Invalid workflow run id: {run_id}")
    return runs_dir(root) / f"{run_id}.json"


def load_run(root: Path, run_id: str) -> dict[str, Any]:
    """Load a local run record."""

    return read_json(_run_path(root, run_id))


def save_run(root: Path, run: dict[str, Any]) -> None:
    """Persist a local run record atomically."""

    if run.get("state") not in STATES:
        raise ConfigurationError(f"Invalid workflow state: {run.get('state')}")
    atomic_write(_run_path(root, run["run_id"]), canonical_json(run))


def start(
    root: Path,
    workflow_name: str,
    plan: str,
    scope: list[str],
    targets: list[str],
    revision: str | None = None,
) -> dict[str, Any]:
    """Create a local, unapproved workflow run."""

    normalized_scope = [value.replace("\\", "/") for value in scope]
    if not normalized_scope or not targets:
        raise ConfigurationError("Workflow scope and target must be non-empty.")
    for pattern in normalized_scope:
        if (
            pattern.startswith("/")
            or "\x00" in pattern
            or any(part == ".." for part in pattern.split("/"))
            or (len(pattern) >= 2 and pattern[1] == ":")
        ):
            raise SafetyError(f"Unsafe workflow scope pattern: {pattern}")
    run_id = f"{workflow_name}-{uuid.uuid4().hex[:10]}"
    run = {
        "schema_version": 1,
        "run_id": run_id,
        "workflow": workflow_name,
        "state": "AWAITING_APPROVAL",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "revision": revision or git_revision(root),
        "plan": plan,
        "scope": normalized_scope,
        "targets": targets,
        "binding": {},
        "approval": None,
        "evidence": [],
        "initial_snapshot": repository_snapshot(root),
        "history": [{"state": "AWAITING_APPROVAL", "at": utc_now()}],
    }
    run["binding"] = binding(run)
    save_run(root, run)
    return run


def binding(run: dict[str, Any]) -> dict[str, str]:
    """Build immutable approval binding values."""

    return {
        "plan_hash": sha256_value(run["plan"]),
        "scope_hash": sha256_value(sorted(run["scope"])),
        "target_hash": sha256_value(sorted(run["targets"])),
        "revision": run["revision"],
    }


def approve(root: Path, run_id: str, actor: str, statement: str) -> dict[str, Any]:
    """Record local human workflow bookkeeping against the current binding."""

    run = load_run(root, run_id)
    if run["state"] != "AWAITING_APPROVAL":
        raise ApprovalError(f"Run must be AWAITING_APPROVAL, got {run['state']}.")
    if git_revision(root) != run["revision"]:
        raise ApprovalError(
            "Repository revision changed; start or re-plan the workflow."
        )
    if not actor.strip() or not statement.strip():
        raise ApprovalError("Approval actor and statement are required.")
    run["approval"] = {
        "kind": "local-workflow-bookkeeping",
        "actor": actor,
        "statement": statement,
        "binding": binding(run),
        "approved_at": utc_now(),
        "limitation": "Not authenticated or tamper-proof authorization.",
    }
    run["state"] = "APPROVED"
    run["updated_at"] = utc_now()
    run["history"].append({"state": "APPROVED", "at": utc_now(), "actor": actor})
    save_run(root, run)
    return run


def assert_current_approval(root: Path, run: dict[str, Any], target: str) -> None:
    """Fail closed if approval is absent, stale, wrong-target, or unreadable."""

    approval = run.get("approval")
    if not approval or run.get("state") not in {"APPROVED", "IMPLEMENTING"}:
        raise ApprovalError("A current approval receipt is required.")
    if approval.get("binding") != binding(run):
        raise ApprovalError("Approval binding is stale or unreadable.")
    if git_revision(root) != run["revision"]:
        raise ApprovalError("Approval revision is stale.")
    if target not in run["targets"]:
        raise ApprovalError(f"Target is not approved: {target}")


def path_in_scope(relative: str, patterns: list[str]) -> bool:
    """Test a portable path against explicit approval scope patterns."""

    relative = relative.replace("\\", "/")
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def enforce_scope(root: Path, run: dict[str, Any]) -> list[str]:
    """Reject changed paths outside scope and baseline control changes."""

    changed = git_changed_paths(root)
    initial = run.get("initial_snapshot", {})
    current = repository_snapshot(root)
    for path in set(initial) | set(current):
        if initial.get(path) != current.get(path):
            changed.append(path)
    violations = sorted(
        {
            path
            for path in changed
            if not path_in_scope(path, run["scope"])
            or any(fnmatch.fnmatch(path, pattern) for pattern in PROTECTED)
        }
    )
    if violations:
        raise ApprovalError(
            "Out-of-scope or protected changes: " + ", ".join(violations)
        )
    return sorted(set(changed))


def record_evidence(
    root: Path,
    run_id: str,
    artifact_paths: list[str],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Bind verification evidence to current artifact bytes."""

    run = load_run(root, run_id)
    if run.get("state") not in {"VERIFYING", "REVIEW_PENDING"}:
        raise ApprovalError(
            "Evidence may be recorded only during verification or review."
        )
    if result.get("status") != "PASS":
        raise ApprovalError(
            "Only passing verification can be recorded as current evidence."
        )
    enforce_scope(root, run)
    invalid_artifacts = [
        path
        for path in artifact_paths
        if not path_in_scope(path, run["scope"])
        or any(fnmatch.fnmatch(path, pattern) for pattern in PROTECTED)
    ]
    if invalid_artifacts:
        raise ApprovalError(
            "Evidence artifacts are outside scope or protected: "
            + ", ".join(invalid_artifacts)
        )
    evidence = {
        "recorded_at": utc_now(),
        "artifact_paths": sorted(artifact_paths),
        "artifact_fingerprint": fingerprint_paths(root, artifact_paths),
        "result": result,
    }
    run["evidence"].append(evidence)
    run["state"] = "AWAITING_ACCEPTANCE"
    run["updated_at"] = utc_now()
    run["history"].append({"state": "AWAITING_ACCEPTANCE", "at": utc_now()})
    save_run(root, run)
    return run


def accept(root: Path, run_id: str, actor: str) -> dict[str, Any]:
    """Accept only current passing evidence for unchanged artifacts."""

    run = load_run(root, run_id)
    if run["state"] != "AWAITING_ACCEPTANCE" or not run["evidence"]:
        raise ApprovalError("Current review evidence is required before acceptance.")
    if not actor.strip():
        raise ApprovalError("Acceptance actor is required.")
    latest = run["evidence"][-1]
    actual = fingerprint_paths(root, latest["artifact_paths"])
    if actual != latest["artifact_fingerprint"]:
        raise ApprovalError("Evidence is stale because an artifact changed.")
    run["state"] = "COMPLETED"
    run["accepted_by"] = actor
    run["accepted_at"] = utc_now()
    run["updated_at"] = utc_now()
    run["history"].append({"state": "COMPLETED", "at": utc_now(), "actor": actor})
    save_run(root, run)
    return run


def resume(root: Path, run_id: str) -> dict[str, Any]:
    """Return current state with explicit staleness observations."""

    run = load_run(root, run_id)
    observations: list[str] = []
    if run.get("approval") and run["approval"].get("binding") != binding(run):
        observations.append("approval-binding-stale")
    if run.get("revision") != git_revision(root):
        observations.append("revision-stale")
    if run.get("evidence"):
        latest = run["evidence"][-1]
        try:
            current = fingerprint_paths(root, latest["artifact_paths"])
            if current != latest["artifact_fingerprint"]:
                observations.append("evidence-stale")
        except SafetyError:
            observations.append("evidence-artifact-unreadable")
    return {"run": run, "observations": observations}


def terminate(root: Path, run_id: str, state: str, reason: str) -> dict[str, Any]:
    """Record a fail-closed terminal or exceptional workflow outcome."""

    if state not in {"BLOCKED", "FAILED", "CANCELLED", "OUTCOME_UNKNOWN"}:
        raise ConfigurationError(f"Unsupported terminal state: {state}")
    if not reason.strip():
        raise ConfigurationError("A terminal-state reason is required.")
    run = load_run(root, run_id)
    run["state"] = state
    run["updated_at"] = utc_now()
    run["history"].append({"state": state, "at": utc_now(), "reason": reason})
    save_run(root, run)
    return run
