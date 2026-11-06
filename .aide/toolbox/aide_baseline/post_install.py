"""Resumable post-installation knowledge generation through Kiro."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import AideError, ConfigurationError, VerificationError
from .guided import (
    FOLDER_SPECS_PROMPT,
    HLD_PROMPT,
    LLD_PROMPT,
    OPENWIKI_MINIMUM,
    OPENWIKI_PROMPT,
    OPENWIKI_UPDATE_PROMPT,
    PROJECT_STEERING_PROMPT,
    REFERENCE_DOCUMENT_SUFFIXES,
    RELATIONSHIP_MAP_PROMPT,
    _confirm,
    _installed_openwiki_version,
    _missing_project_steering,
    _node_version,
    _reference_document_suffix,
    _run_checked,
    _run_kiro_prompt,
    _safe_registry,
    _validate_project_steering,
    _version_tuple,
    validate_okf,
)
from .installer import validate_project
from .util import atomic_write, canonical_json, find_git_root, read_json, utc_now

STATE_SCHEMA_VERSION = 1
STATE_RELATIVE_PATH = ".aide/local/post-install-state.json"
DEFAULT_OPENWIKI_PACKAGE = "openwiki@0.4.3"
OPENWIKI_AGENT = "aide-openwiki"
PHASE_ORDER = (
    "openwiki_package",
    "openwiki_initialize",
    "knowledge_base",
    "hld",
    "lld",
    "folder_specs",
    "relationship_map",
    "openwiki_update",
    "project_steering",
)
OPTIONAL_PHASES = frozenset(
    {"folder_specs", "relationship_map", "openwiki_update"}
)
PROMPT_PHASES = (
    ("hld", HLD_PROMPT, "aide-architect", "knowledge-base/HLD.md"),
    ("lld", LLD_PROMPT, "aide-architect", "knowledge-base/LLD.md"),
    ("folder_specs", FOLDER_SPECS_PROMPT, "aide-spec-planner", "SPECS.md"),
    (
        "relationship_map",
        RELATIONSHIP_MAP_PROMPT,
        "aide-knowledge-curator",
        "knowledge-base/SPECS-RELATIONSHIP-MAP.md",
    ),
)


def _state_path(root: Path) -> Path:
    return root / STATE_RELATIVE_PATH


def _new_state(root: Path, reference_documents: list[Path]) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "workflow": "aide-post-install-knowledge",
        "target": str(root),
        "created_at": now,
        "updated_at": now,
        "status": "running",
        "current_phase": None,
        "reference_documents": [str(path) for path in reference_documents],
        "phases": {
            name: {"status": "pending", "attempts": 0} for name in PHASE_ORDER
        },
        "history": [],
    }


def _load_state(root: Path) -> dict[str, Any] | None:
    path = _state_path(root)
    if not path.exists():
        return None
    state = read_json(path)
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != STATE_SCHEMA_VERSION
        or state.get("workflow") != "aide-post-install-knowledge"
        or not isinstance(state.get("phases"), dict)
    ):
        raise ConfigurationError(f"Unsupported post-install state: {path}")
    if state.get("target") != str(root):
        raise ConfigurationError(
            "Post-install state belongs to a different repository root."
        )
    return state


def _save_state(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_write(_state_path(root), canonical_json(state))


def _record_transition(
    root: Path,
    state: dict[str, Any],
    phase: str,
    status: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    record = state["phases"].setdefault(phase, {"status": "pending", "attempts": 0})
    previous = record.get("status", "pending")
    record["status"] = status
    record["updated_at"] = utc_now()
    if message:
        record["message"] = message
    else:
        record.pop("message", None)
    if details:
        record["details"] = details
    if status == "running":
        record["attempts"] = int(record.get("attempts", 0)) + 1
        record["started_at"] = utc_now()
        state["current_phase"] = phase
    else:
        state["current_phase"] = None
    if status in {"complete", "preserved"}:
        record["completed_at"] = utc_now()
    state["history"].append(
        {
            "at": utc_now(),
            "phase": phase,
            "from": previous,
            "to": status,
            "message": message or "",
        }
    )
    _save_state(root, state)


def _recover_stale_checkpoint(root: Path, state: dict[str, Any]) -> None:
    recovered = False
    for phase, record in state["phases"].items():
        if record.get("status") == "running":
            _record_transition(
                root,
                state,
                phase,
                "interrupted",
                "Previous process stopped while this phase was running; retry queued.",
            )
            recovered = True
    if recovered:
        state["status"] = "recovering"
        _save_state(root, state)


def _validate_nonempty(root: Path, relative: str) -> list[str]:
    path = root / relative
    if not path.is_file():
        return [f"{relative} is missing"]
    if not path.read_text(encoding="utf-8", errors="ignore").strip():
        return [f"{relative} is empty"]
    return []


def _openwiki_lifecycle_errors(
    root: Path, *, expected_command: str | None = None
) -> list[str]:
    errors = validate_okf(root)
    marker = root / "openwiki" / ".last-update.json"
    if not marker.is_file():
        return [*errors, "openwiki/.last-update.json is missing"]
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [*errors, f"openwiki/.last-update.json is unreadable: {exc}"]
    if not isinstance(payload, dict):
        return [*errors, "openwiki/.last-update.json must contain an object"]
    status = payload.get("status")
    if status != "complete":
        errors.append(
            "OpenWiki lifecycle is not complete: "
            f"openwiki/.last-update.json status is {status!r}"
        )
    command = payload.get("command")
    if expected_command is not None and command != expected_command:
        errors.append(
            "OpenWiki lifecycle did not run the required command: "
            f"expected {expected_command!r}, found {command!r}"
        )
    return errors


def _openwiki_command_errors() -> list[str]:
    return [] if shutil.which("openwiki") else ["openwiki is unavailable on PATH"]


def _directory_errors(root: Path, relative: str) -> list[str]:
    return [] if (root / relative).is_dir() else [f"{relative} is missing"]


def _run_phase(
    root: Path,
    state: dict[str, Any],
    name: str,
    action: Callable[[], dict[str, Any] | None],
    validate: Callable[[], list[str]],
    *,
    mandatory: bool = True,
) -> bool:
    record = state["phases"].setdefault(name, {"status": "pending", "attempts": 0})
    if record.get("status") in {"complete", "preserved"}:
        errors = validate()
        if not errors:
            print(f"==> Resume: {name} already complete")
            return True
        _record_transition(
            root,
            state,
            name,
            "stale",
            "Recorded output no longer validates: " + "; ".join(errors),
        )

    _record_transition(root, state, name, "running")
    print(f"\n==> Post-install phase: {name}")
    try:
        details = action() or {}
        errors = validate()
        if errors:
            raise VerificationError("; ".join(errors))
    except KeyboardInterrupt:
        _record_transition(
            root,
            state,
            name,
            "interrupted",
            "Interrupted by the operator; this phase will be retried.",
        )
        state["status"] = "interrupted"
        _save_state(root, state)
        raise
    except Exception as exc:
        phase_status = "failed" if mandatory else "optional_failed"
        message = str(exc)[:1000] or type(exc).__name__
        _record_transition(root, state, name, phase_status, message)
        state["status"] = "failed" if mandatory else "running_with_warnings"
        _save_state(root, state)
        if mandatory:
            raise
        print(
            f"WARNING: optional phase {name} did not complete: {message}. "
            "Continuing with the remaining workflow.",
            file=sys.stderr,
        )
        return False
    _record_transition(root, state, name, "complete", details=details)
    return True


def _resolve_reference_documents(root: Path, values: list[str]) -> list[Path]:
    documents: list[Path] = []
    seen: set[Path] = set()
    for supplied in values:
        for value in supplied.split(";"):
            value = value.strip()
            if not value:
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                candidate = candidate.resolve(strict=True)
            except OSError as exc:
                raise ConfigurationError(
                    f"Reference document is not readable: {candidate}"
                ) from exc
            if not candidate.is_file():
                raise ConfigurationError(
                    f"Reference document is not a regular file: {candidate}"
                )
            if candidate.suffix.lower() not in REFERENCE_DOCUMENT_SUFFIXES:
                supported = ", ".join(sorted(REFERENCE_DOCUMENT_SUFFIXES))
                raise ConfigurationError(
                    f"Reference document must be one of {supported}: {candidate}"
                )
            if candidate not in seen:
                seen.add(candidate)
                documents.append(candidate)
    return documents


def _require_workspace(root: Path) -> None:
    project_path = root / ".aide" / "project.json"
    if not project_path.is_file():
        raise ConfigurationError(
            "AIDE is not installed. Apply the baseline overlay before post-install."
        )
    validate_project(read_json(project_path))
    required_prompts = [OPENWIKI_PROMPT, OPENWIKI_UPDATE_PROMPT]
    required_prompts.extend(item[1] for item in PROMPT_PHASES)
    required_prompts.append(PROJECT_STEERING_PROMPT)
    missing = [
        relative
        for relative in required_prompts
        if not (root / relative).is_file()
    ]
    if missing:
        raise ConfigurationError(
            "Required installed prompts are missing: " + ", ".join(missing)
        )
    mcp_path = root / ".kiro" / "settings" / "mcp.json"
    mcp = read_json(mcp_path) if mcp_path.is_file() else {}
    workspace_openwiki = mcp.get("mcpServers", {}).get("openwiki")
    if not isinstance(workspace_openwiki, dict) or workspace_openwiki.get(
        "disabled", False
    ):
        raise ConfigurationError(
            "The workspace OpenWiki MCP must be present and enabled. "
            "Use the full baseline flavor or add a reviewed workspace entry."
        )
    agent_path = root / ".kiro" / "agents" / f"{OPENWIKI_AGENT}.json"
    agent = read_json(agent_path) if agent_path.is_file() else {}
    agent_openwiki = agent.get("mcpServers", {}).get("openwiki")
    if not isinstance(agent_openwiki, dict) or agent_openwiki.get("disabled", False):
        raise ConfigurationError(
            f"The dedicated {OPENWIKI_AGENT} agent must embed an enabled "
            "OpenWiki MCP server. Reapply or update the full AIDE baseline."
        )
    if "@openwiki" not in agent.get("tools", []):
        raise ConfigurationError(
            f"The dedicated {OPENWIKI_AGENT} agent must expose @openwiki tools."
        )
    if not shutil.which("kiro-cli"):
        raise ConfigurationError("kiro-cli is required for post-install generation.")


def _ensure_openwiki_available(
    root: Path,
    *,
    package: str,
    dependency_mode: str,
    skip_install: bool,
    assume_yes: bool,
    interactive: bool,
) -> dict[str, Any]:
    current = _installed_openwiki_version()
    executable = bool(shutil.which("openwiki"))
    parsed = _version_tuple(current)
    if executable and (parsed is None or parsed >= OPENWIKI_MINIMUM):
        return {"version": current or "unknown", "installation": "preserved"}
    if skip_install:
        raise ConfigurationError(
            "OpenWiki installation was skipped, but a compatible command is "
            "unavailable."
        )
    missing = [name for name in ("node", "npm") if not shutil.which(name)]
    if missing:
        raise ConfigurationError(
            "Installing OpenWiki requires: " + ", ".join(missing)
        )
    node = _version_tuple(_node_version())
    if node and node[0] < 22:
        raise ConfigurationError("Installing OpenWiki requires Node.js 22 or newer.")
    _confirm(
        f"Install {package} globally from npm source {_safe_registry()}?",
        assume_yes=assume_yes,
        interactive=interactive,
    )
    args = ["npm", "install", "--global"]
    if dependency_mode == "offline":
        args.append("--offline")
    args.append(package)
    _run_checked(f"Install {package}", args, cwd=root)
    if not shutil.which("openwiki"):
        raise VerificationError(
            "npm completed, but the openwiki command is unavailable on PATH."
        )
    return {
        "version": _installed_openwiki_version() or "unknown",
        "installation": "installed",
    }


def _create_knowledge_base(root: Path) -> dict[str, Any]:
    path = root / "knowledge-base"
    if path.exists() and not path.is_dir():
        raise ConfigurationError("knowledge-base exists but is not a directory.")
    path.mkdir(parents=True, exist_ok=True)
    return {"path": "knowledge-base"}


def _initialize_openwiki(root: Path) -> dict[str, Any]:
    _run_kiro_prompt(
        root,
        OPENWIKI_PROMPT,
        agent=OPENWIKI_AGENT,
        suffix=(
            "Activate the installed OpenWiki workspace skill when required by "
            "the Kiro client. Initialize this repository's OpenWiki from the "
            "current source and tests, and resume any existing lifecycle run."
        ),
    )
    return {"mode": "initialize-or-resume"}


def _prompt_action(
    root: Path,
    prompt: str,
    agent: str,
    evidence_suffix: str,
) -> Callable[[], dict[str, Any]]:
    def run() -> dict[str, Any]:
        _run_kiro_prompt(
            root,
            prompt,
            agent=agent,
            suffix=evidence_suffix,
        )
        return {"prompt": prompt, "agent": agent}

    return run


def _run_steering(root: Path) -> dict[str, Any]:
    missing = _missing_project_steering(root)
    if not missing:
        return {"requested_files": [], "result": "all files already existed"}
    selected = "\n".join(f"- `{relative}`" for relative in missing)
    _run_kiro_prompt(
        root,
        PROJECT_STEERING_PROMPT,
        agent="aide-architect",
        suffix="Create exactly these missing files and no others:\n" + selected,
    )
    errors = _validate_project_steering(root, missing)
    if errors:
        raise VerificationError("; ".join(errors))
    return {"requested_files": missing}


def _steering_errors(root: Path, state: dict[str, Any]) -> list[str]:
    record = state["phases"].get("project_steering", {})
    requested = record.get("details", {}).get("requested_files", [])
    if not requested:
        return [] if not _missing_project_steering(root) else [
            "project steering has not been generated"
        ]
    return _validate_project_steering(root, requested)


def run_post_install(
    target: Path,
    *,
    reference_documents: list[Path] | None = None,
    openwiki_package: str = DEFAULT_OPENWIKI_PACKAGE,
    dependency_mode: str = "configured",
    skip_openwiki_install: bool = False,
    assume_yes: bool = False,
    interactive: bool = True,
) -> dict[str, Any]:
    """Run or resume the ordered post-installation knowledge workflow."""

    root = find_git_root(target)
    _require_workspace(root)
    state = _load_state(root)
    supplied_documents = (
        _resolve_reference_documents(
            root, [str(path) for path in reference_documents]
        )
        if reference_documents is not None
        else None
    )
    if state is None:
        documents = supplied_documents or []
        state = _new_state(root, documents)
        _save_state(root, state)
    else:
        _recover_stale_checkpoint(root, state)
        saved_documents = _resolve_reference_documents(
            root, list(state.get("reference_documents", []))
        )
        if supplied_documents is not None and supplied_documents != saved_documents:
            raise ConfigurationError(
                "Reference documents differ from the resumable checkpoint. "
                "Resume with the recorded inputs."
            )
        documents = saved_documents

    evidence_suffix = _reference_document_suffix(documents)
    state["status"] = "running"
    state["configuration"] = {
        "dependency_mode": dependency_mode,
        "openwiki_package": openwiki_package,
        "skip_openwiki_install": skip_openwiki_install,
    }
    _save_state(root, state)

    _run_phase(
        root,
        state,
        "openwiki_package",
        lambda: _ensure_openwiki_available(
            root,
            package=openwiki_package,
            dependency_mode=dependency_mode,
            skip_install=skip_openwiki_install,
            assume_yes=assume_yes,
            interactive=interactive,
        ),
        _openwiki_command_errors,
    )

    if not _openwiki_lifecycle_errors(root) and state["phases"][
        "openwiki_initialize"
    ].get("status") == "pending":
        _record_transition(
            root,
            state,
            "openwiki_initialize",
            "preserved",
            "Existing OpenWiki passes the OKF root checks.",
        )
    else:
        _run_phase(
            root,
            state,
            "openwiki_initialize",
            lambda: _initialize_openwiki(root),
            lambda: _openwiki_lifecycle_errors(root),
        )

    _run_phase(
        root,
        state,
        "knowledge_base",
        lambda: _create_knowledge_base(root),
        lambda: _directory_errors(root, "knowledge-base"),
    )

    for name, prompt, agent, artifact in PROMPT_PHASES:
        _run_phase(
            root,
            state,
            name,
            _prompt_action(root, prompt, agent, evidence_suffix),
            lambda relative=artifact: _validate_nonempty(root, relative),
            mandatory=name not in OPTIONAL_PHASES,
        )

    _run_phase(
        root,
        state,
        "openwiki_update",
        _prompt_action(root, OPENWIKI_UPDATE_PROMPT, OPENWIKI_AGENT, ""),
        lambda: _openwiki_lifecycle_errors(root, expected_command="update"),
        mandatory=False,
    )

    if not _missing_project_steering(root) and state["phases"][
        "project_steering"
    ].get("status") == "pending":
        _record_transition(
            root,
            state,
            "project_steering",
            "preserved",
            "All project steering files already exist.",
            {"requested_files": []},
        )
    else:
        _run_phase(
            root,
            state,
            "project_steering",
            lambda: _run_steering(root),
            lambda: _steering_errors(root, state),
        )

    optional_failures = [
        {
            "phase": name,
            "message": str(state["phases"][name].get("message", "")),
        }
        for name in PHASE_ORDER
        if name in OPTIONAL_PHASES
        and state["phases"][name].get("status") == "optional_failed"
    ]
    if optional_failures:
        state["status"] = "complete_with_warnings"
        state["warnings"] = optional_failures
    else:
        state["status"] = "complete"
        state.pop("warnings", None)
    state["current_phase"] = None
    state["completed_at"] = utc_now()
    _save_state(root, state)
    return state


def post_install_status(target: Path) -> dict[str, Any]:
    root = find_git_root(target)
    state = _load_state(root)
    return state or {
        "schema_version": STATE_SCHEMA_VERSION,
        "workflow": "aide-post-install-knowledge",
        "target": str(root),
        "status": "not_started",
        "state_file": STATE_RELATIVE_PATH,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aide-post-install",
        description=(
            "Install OpenWiki when needed and run or resume the ordered Kiro "
            "knowledge-generation workflow."
        ),
    )
    parser.add_argument("--target", default=".")
    parser.add_argument("--reference-document", action="append")
    parser.add_argument("--openwiki-package", default=DEFAULT_OPENWIKI_PACKAGE)
    parser.add_argument(
        "--dependency-mode",
        choices=["offline", "configured"],
        default="configured",
    )
    parser.add_argument("--skip-openwiki-install", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        root = find_git_root(Path(args.target))
        if args.status:
            print(json.dumps(post_install_status(root), indent=2, sort_keys=True))
            return 0
        interactive = sys.stdin.isatty()
        if not interactive:
            raise ConfigurationError(
                "Post-install generation requires an interactive terminal for "
                "Kiro tool approvals."
            )
        existing = _load_state(root)
        references: list[Path] | None
        if args.reference_document:
            references = _resolve_reference_documents(root, args.reference_document)
        elif existing is None:
            response = input(
                "Existing HLD, LLD, or related .pdf, .docx, or Markdown paths "
                "(semicolon-separated; blank for none): "
            ).strip()
            references = _resolve_reference_documents(root, [response])
        else:
            references = None
        result = run_post_install(
            root,
            reference_documents=references,
            openwiki_package=args.openwiki_package,
            dependency_mode=args.dependency_mode,
            skip_openwiki_install=args.skip_openwiki_install,
            assume_yes=args.yes,
            interactive=interactive,
        )
        if result.get("status") == "complete_with_warnings":
            print(
                "\nCOMPLETE WITH WARNINGS: mandatory knowledge phases finished; "
                "review optional phase warnings."
            )
        else:
            print("\nCOMPLETE: resumable AIDE post-install workflow finished.")
        print(f"Checkpoint: {root / STATE_RELATIVE_PATH}")
        print("Review OpenWiki, knowledge-base, specifications, and steering drafts.")
        return 0 if result.get("status") in {
            "complete",
            "complete_with_warnings",
        } else 2
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the same command to resume.", file=sys.stderr)
        return 130
    except AideError as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error": type(exc).__name__,
                    "message": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return exc.exit_code
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "ERROR", "error": type(exc).__name__, "message": str(exc)},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
