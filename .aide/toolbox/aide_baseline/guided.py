"""Interactive, resumable installation of the complete AIDE workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .errors import AideError, ConfigurationError, ConflictError, VerificationError
from .installer import baseline_version, install
from .profiles import detect_profiles
from .util import find_git_root, utc_now

FULL_COMPONENTS = ["shared", "workflows", "profiles", "optional-agents"]
OPENWIKI_MINIMUM = (0, 4, 3)
OPENWIKI_PROMPT = "prompt/initialize-openwiki-okf-with-kiro.md"
HLD_PROMPT = "prompt/generate-hld-with-kiro.md"
LLD_PROMPT = "prompt/generate-lld-with-kiro.md"
FOLDER_SPECS_PROMPT = "prompt/generate-folder-specs-with-kiro.md"
RELATIONSHIP_MAP_PROMPT = "prompt/generate-specs-relationship-map-with-kiro.md"
OPENWIKI_UPDATE_PROMPT = "prompt/update-openwiki-from-knowledge-base-with-kiro.md"
PROJECT_STEERING_PROMPT = "prompt/generate-project-steering-with-kiro.md"
PROJECT_STEERING_FILES = (
    ".kiro/steering/product.md",
    ".kiro/steering/structure.md",
    ".kiro/steering/tech.md",
)
REFERENCE_DOCUMENT_SUFFIXES = {".docx", ".md", ".markdown", ".pdf"}
RUNTIME_PROJECTS = (
    ".aide/full/hook",
    ".aide/full/mcp-servers/aide-knowledge-mcp",
    ".aide/full/mcp-servers/aide-architecture-mcp",
    ".aide/full/mcp-servers/aide-spec-mcp",
    ".aide/full/mcp-servers/aide-azure-mcp",
    ".aide/full/mcp-servers/aide-azure-change-mcp",
    ".aide/full/mcp-servers/aide-kubernetes-mcp",
    ".aide/full/mcp-servers/aide-kubernetes-change-mcp",
    ".aide/full/mcp-servers/aide-token-saver",
    ".aide/full/spec-brain",
    ".aide/full/scas",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guided-install",
        description=(
            "Install the complete AIDE baseline, prepare local runtimes, install "
            "OpenWiki, and initialize OKF through Kiro."
        ),
    )
    parser.add_argument("--target")
    parser.add_argument("--profile", "--profiles", action="append")
    parser.add_argument(
        "--kiro-target", choices=["auto", "current", "cli2"], default="auto"
    )
    parser.add_argument("--security-mode", choices=["kiro-approved", "strict-local"])
    parser.add_argument("--dependency-mode", choices=["offline", "configured"])
    parser.add_argument("--openwiki-package", default="openwiki@0.4.3")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--skip-runtime-sync", action="store_true")
    parser.add_argument("--skip-openwiki-install", action="store_true")
    parser.add_argument("--skip-openwiki-generation", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _split(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [
        item.strip() for value in values for item in value.split(",") if item.strip()
    ]


def _choice(
    value: str | None,
    *,
    prompt: str,
    choices: dict[str, str],
    default: str,
    interactive: bool,
) -> str:
    if value:
        return value
    if not interactive:
        raise ConfigurationError(
            f"Non-interactive guided installation requires an explicit {prompt}."
        )
    while True:
        response = input(f"{prompt} [{default}]: ").strip().lower() or default
        if response in choices:
            return choices[response]
        print("Choose " + ", ".join(sorted(choices)) + ".")


def _confirm(message: str, *, assume_yes: bool, interactive: bool) -> None:
    if assume_yes:
        return
    if not interactive:
        raise ConfigurationError(
            f"Confirmation required: {message} Re-run interactively or pass --yes."
        )
    response = input(f"{message} [y/N]: ").strip().lower()
    if response not in {"y", "yes"}:
        raise ConfigurationError("Guided installation cancelled by the operator.")


def _ask_yes_no(message: str, *, interactive: bool, default: bool = False) -> bool:
    """Ask an optional, fail-closed interactive question."""

    if not interactive:
        return False
    suffix = "[Y/n]" if default else "[y/N]"
    response = input(f"{message} {suffix}: ").strip().lower()
    if not response:
        return default
    return response in {"y", "yes"}


def _resolve_reference_documents(root: Path) -> list[Path]:
    """Validate semicolon-separated, operator-approved supplemental documents."""

    response = input(
        "Existing HLD, LLD, or related document paths "
        "(semicolon-separated; blank for none): "
    ).strip()
    if not response:
        return []

    documents: list[Path] = []
    seen: set[Path] = set()
    for value in response.split(";"):
        candidate = Path(value.strip()).expanduser()
        if not value.strip():
            continue
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise ConfigurationError(
                f"Reference document is not a readable file: {candidate}"
            )
        if candidate.suffix.lower() not in REFERENCE_DOCUMENT_SUFFIXES:
            supported = ", ".join(sorted(REFERENCE_DOCUMENT_SUFFIXES))
            raise ConfigurationError(
                f"Reference document must be one of {supported}: {candidate}"
            )
        if candidate not in seen:
            seen.add(candidate)
            documents.append(candidate)
    if not documents:
        raise ConfigurationError("No usable reference documents were supplied.")
    return documents


def _resolve_root(value: str | None, interactive: bool) -> Path:
    target = value
    if target is None and interactive:
        response = input(f"Target Git repository [{Path.cwd()}]: ").strip()
        target = response or "."
    return find_git_root(Path(target or "."))


def _resolve_profiles(
    root: Path, values: list[str] | None, interactive: bool
) -> list[str]:
    explicit = _split(values)
    if explicit:
        return sorted(set(explicit))
    detected = [item for item in detect_profiles(root)["profiles"] if item != "mixed"]
    suggested = detected or ["mixed"]
    if not interactive:
        return sorted(set(suggested))
    default = ",".join(suggested)
    response = input(f"Repository profiles [{default}]: ").strip()
    return sorted(set(_split([response]) if response else suggested))


def _platform_command(args: list[str]) -> list[str]:
    """Resolve Windows command shims without enabling a general shell."""

    resolved = shutil.which(args[0])
    if not resolved:
        return args
    path = Path(resolved)
    if (
        os.name == "nt"
        and args[0] == "npm"
        and path.suffix.lower()
        in {
            ".cmd",
            ".bat",
        }
    ):
        npm_cli = path.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        node = shutil.which("node")
        if node and npm_cli.is_file():
            return [node, str(npm_cli), *args[1:]]
    return [resolved, *args[1:]]


def _capture(
    args: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            _platform_command(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ConfigurationError(f"Could not execute {args[0]}: {exc}") from exc


def _run_checked(
    label: str,
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"\n==> {label}")
    try:
        completed = subprocess.run(
            _platform_command(args),
            cwd=cwd,
            env=env,
            capture_output=capture,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError(f"{args[0]} is not available on PATH.") from exc
    if completed.returncode:
        detail = ""
        if capture:
            detail = (completed.stderr or completed.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise VerificationError(
            f"{label} failed with exit code {completed.returncode}{suffix}"
        )
    return completed


def _node_version() -> str | None:
    if not shutil.which("node"):
        return None
    completed = _capture(["node", "--version"])
    return completed.stdout.strip() if completed.returncode == 0 else None


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return None
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def _installed_openwiki_version() -> str | None:
    if not shutil.which("npm"):
        return None
    completed = _capture(["npm", "list", "--global", "--depth=0", "--json", "openwiki"])
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None
    value = payload.get("dependencies", {}).get("openwiki", {}).get("version")
    return value if isinstance(value, str) else None


def _safe_registry() -> str:
    if not shutil.which("npm"):
        return "unavailable"
    completed = _capture(["npm", "config", "get", "registry"])
    value = completed.stdout.strip() if completed.returncode == 0 else "unknown"
    return re.sub(r"(//)[^/@]+@", r"\1***@", value)


def _preflight(root: Path) -> dict[str, Any]:
    commands = {
        name: shutil.which(name)
        for name in ("git", "kiro-cli", "node", "npm", "uv", "openwiki")
    }
    return {
        "root": str(root),
        "commands": {name: bool(path) for name, path in commands.items()},
        "node_version": _node_version(),
        "openwiki_version": _installed_openwiki_version(),
        "npm_registry": _safe_registry(),
        "dirty_worktree": bool(
            _capture(["git", "-C", str(root), "status", "--porcelain"]).stdout.strip()
        ),
    }


def _require_preflight(
    preflight: dict[str, Any],
    *,
    security_mode: str,
    skip_runtime_sync: bool,
    skip_openwiki_install: bool,
    skip_openwiki_generation: bool,
) -> None:
    commands = preflight["commands"]
    missing: list[str] = []
    if not skip_runtime_sync and not commands["uv"]:
        missing.append("uv")
    if not skip_openwiki_install and (not commands["node"] or not commands["npm"]):
        missing.extend(name for name in ("node", "npm") if not commands[name])
    generation_enabled = (
        security_mode == "kiro-approved" and not skip_openwiki_generation
    )
    if generation_enabled and not commands["kiro-cli"]:
        missing.append("kiro-cli")
    if missing:
        raise ConfigurationError(
            "Missing required commands: " + ", ".join(sorted(set(missing)))
        )
    node = _version_tuple(preflight.get("node_version"))
    if not skip_openwiki_install and node and node[0] < 22:
        raise ConfigurationError(
            f"Node.js 22 or newer is required; found {preflight['node_version']}."
        )
    if (
        skip_openwiki_install
        and not commands["openwiki"]
        and not skip_openwiki_generation
    ):
        raise ConfigurationError(
            "OpenWiki installation was skipped, but the openwiki command is "
            "unavailable."
        )


def _write_state(root: Path, phases: dict[str, Any]) -> None:
    path = root / ".aide" / "local" / "guided-install-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": utc_now(),
        "phases": phases,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _prepare_runtimes(
    root: Path, *, dependency_mode: str, skip: bool, phases: dict[str, Any]
) -> None:
    if skip:
        phases["runtimes"] = "skipped"
        _write_state(root, phases)
        return
    for relative in RUNTIME_PROJECTS:
        args = [
            "uv",
            "sync",
            "--project",
            str(root / relative),
            "--all-groups",
            "--frozen",
        ]
        if dependency_mode == "offline":
            args.append("--offline")
        _run_checked(f"Prepare {relative}", args, cwd=root)
    phases["runtimes"] = "prepared"
    _write_state(root, phases)


def _ensure_openwiki(
    root: Path,
    *,
    package: str,
    dependency_mode: str,
    skip: bool,
    assume_yes: bool,
    interactive: bool,
    phases: dict[str, Any],
) -> None:
    current = _installed_openwiki_version()
    executable = bool(shutil.which("openwiki"))
    parsed = _version_tuple(current)
    needs_install = not executable or (parsed is not None and parsed < OPENWIKI_MINIMUM)
    if skip:
        if not executable:
            raise ConfigurationError(
                "OpenWiki installation was skipped and openwiki is unavailable."
            )
        phases["openwiki_package"] = f"preserved ({current or 'version unknown'})"
        _write_state(root, phases)
        return
    if needs_install:
        _confirm(
            (
                f"Install {package} globally using npm's configured source "
                f"({_safe_registry()})?"
            ),
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
                "npm completed, but the openwiki command is still unavailable on PATH."
            )
        current = _installed_openwiki_version()
    phases["openwiki_package"] = f"available ({current or 'version unknown'})"
    _write_state(root, phases)


def _validate_agents(root: Path) -> None:
    for path in sorted((root / ".kiro" / "agents").glob("*.json")):
        _run_checked(
            f"Validate agent {path.stem}",
            ["kiro-cli", "agent", "validate", "--path", str(path)],
            cwd=root,
            capture=True,
        )


def _openwiki_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["OPENWIKI_TELEMETRY_DISABLED"] = "1"
    environment["DO_NOT_TRACK"] = "1"
    return environment


def _run_kiro_prompt(
    root: Path, relative: str, *, agent: str, suffix: str = ""
) -> None:
    path = root / relative
    if not path.is_file():
        raise ConfigurationError(f"Required installed prompt is missing: {relative}")
    prompt = path.read_text(encoding="utf-8")
    if suffix:
        prompt = f"{prompt.rstrip()}\n\n{suffix.strip()}\n"
    print(
        "Kiro opens an interactive chat for this step. Complete only the "
        "requested prompt. Do not exit while Kiro shows active progress (for "
        "example, a `◔` percentage). Wait until it reports the requested file "
        "was created, then use Kiro's normal exit command (normally `/exit`) "
        "to return control to this AIDE workflow."
    )
    _run_checked(
        f"Run Kiro prompt {relative}",
        ["kiro-cli", "chat", "--agent", agent, prompt],
        cwd=root,
        env=_openwiki_environment(),
    )
    print(f"Kiro returned control after {relative}; validating the requested output.")


def validate_okf(root: Path) -> list[str]:
    errors: list[str] = []
    index = root / "openwiki" / "index.md"
    quickstart = root / "openwiki" / "quickstart.md"
    if not index.is_file():
        errors.append("openwiki/index.md is missing")
    else:
        text = index.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"(?m)^okf_version:\s*[\"']?0\.2[\"']?\s*$", text):
            errors.append('openwiki/index.md does not declare okf_version: "0.2"')
    if not quickstart.is_file():
        errors.append("openwiki/quickstart.md is missing")
    return errors


def _require_nonempty_file(root: Path, relative: str) -> None:
    path = root / relative
    if (
        not path.is_file()
        or not path.read_text(encoding="utf-8", errors="ignore").strip()
    ):
        raise VerificationError(f"Kiro did not create a non-empty {relative}.")


def _reference_document_suffix(documents: list[Path]) -> str:
    if not documents:
        return (
            "No operator-supplied architecture documents are available. "
            "Use the current repository source and tests as the evidence base."
        )
    paths = "\n".join(f"- `{path}`" for path in documents)
    return (
        "The operator approved these supplemental local documents for this "
        "documentation run:\n"
        f"{paths}\n\n"
        "Read them as contextual draft input only. Do not modify or copy them. "
        "Current repository source, schemas, and tests remain authoritative; "
        "label any conflict or unsupported claim for review."
    )


def _missing_project_steering(root: Path) -> list[str]:
    return [
        relative
        for relative in PROJECT_STEERING_FILES
        if not (root / relative).is_file()
    ]


def _validate_project_steering(root: Path, paths: list[str]) -> list[str]:
    errors: list[str] = []
    for relative in paths:
        path = root / relative
        if not path.is_file():
            errors.append(f"{relative} is missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"(?m)^inclusion:\s*always\s*$", text):
            errors.append(f"{relative} does not declare inclusion: always")
    return errors


def _run_optional_knowledge_generation(
    root: Path,
    *,
    security_mode: str,
    interactive: bool,
    phases: dict[str, Any],
) -> None:
    """Run the explicitly approved Kiro knowledge sequence after installation."""

    if security_mode != "kiro-approved":
        phases["knowledge_generation"] = {"status": "deferred: strict-local mode"}
        _write_state(root, phases)
        return
    if not interactive:
        phases["knowledge_generation"] = {
            "status": "not requested: interactive confirmation required"
        }
        _write_state(root, phases)
        return
    if not _ask_yes_no("Do you want to generate the knowledge-base?", interactive=True):
        phases["knowledge_generation"] = {"status": "declined"}
        _write_state(root, phases)
        return

    documents: list[Path] = []
    if _ask_yes_no(
        "Do you want to use existing HLD, LLD, or related documents?",
        interactive=True,
    ):
        documents = _resolve_reference_documents(root)
    evidence_suffix = _reference_document_suffix(documents)
    state: dict[str, Any] = {
        "status": "running",
        "reference_document_count": len(documents),
    }
    phases["knowledge_generation"] = state
    _write_state(root, phases)

    for name, prompt, agent, artifact in (
        ("hld", HLD_PROMPT, "aide-architect", "knowledge-base/HLD.md"),
        ("lld", LLD_PROMPT, "aide-architect", "knowledge-base/LLD.md"),
        ("folder_specs", FOLDER_SPECS_PROMPT, "aide-spec-planner", "SPECS.md"),
        (
            "relationship_map",
            RELATIONSHIP_MAP_PROMPT,
            "aide-knowledge-curator",
            "knowledge-base/SPECS-RELATIONSHIP-MAP.md",
        ),
    ):
        state[name] = "running"
        _write_state(root, phases)
        _run_kiro_prompt(root, prompt, agent=agent, suffix=evidence_suffix)
        _require_nonempty_file(root, artifact)
        state[name] = "complete"
        _write_state(root, phases)

    if not _ask_yes_no(
        "Do you want to update OpenWiki based on the knowledge-base?",
        interactive=True,
    ):
        state["openwiki_update"] = "declined; optional sequence stopped"
        state["status"] = "complete"
        _write_state(root, phases)
        return
    existing_errors = validate_okf(root)
    if existing_errors:
        raise ConfigurationError(
            "Cannot update OpenWiki before a valid first-generation wiki exists: "
            + "; ".join(existing_errors)
        )
    state["openwiki_update"] = "running"
    _write_state(root, phases)
    _run_kiro_prompt(root, OPENWIKI_UPDATE_PROMPT, agent="kiro_default")
    errors = validate_okf(root)
    if errors:
        state["openwiki_update"] = "incomplete; resumable state preserved"
        _write_state(root, phases)
        raise VerificationError("; ".join(errors))
    state["openwiki_update"] = "complete"
    _write_state(root, phases)

    if not _ask_yes_no(
        "Do you want to create project steering files based on the knowledge-base?",
        interactive=True,
    ):
        state["project_steering"] = "declined"
        state["status"] = "complete"
        _write_state(root, phases)
        return
    missing = _missing_project_steering(root)
    if not missing:
        state["project_steering"] = "preserved: all target files already exist"
    else:
        selected = "\n".join(f"- `{relative}`" for relative in missing)
        state["project_steering"] = "running"
        _write_state(root, phases)
        _run_kiro_prompt(
            root,
            PROJECT_STEERING_PROMPT,
            agent="aide-architect",
            suffix=("Create exactly these missing files and no others:\n" + selected),
        )
        errors = _validate_project_steering(root, missing)
        if errors:
            state["project_steering"] = {"status": "incomplete", "errors": errors}
            _write_state(root, phases)
            raise VerificationError("; ".join(errors))
        state["project_steering"] = "complete"
    state["status"] = "complete"
    _write_state(root, phases)


def guided_install(
    args: argparse.Namespace,
    *,
    source_root: Path,
    interactive: bool,
) -> dict[str, Any]:
    root = _resolve_root(args.target, interactive)
    profiles = _resolve_profiles(root, args.profile, interactive)
    security_mode = _choice(
        args.security_mode,
        prompt="Security mode",
        choices={
            "1": "kiro-approved",
            "kiro-approved": "kiro-approved",
            "2": "strict-local",
            "strict-local": "strict-local",
        },
        default="kiro-approved",
        interactive=interactive,
    )
    dependency_mode = _choice(
        args.dependency_mode,
        prompt="Dependency source mode",
        choices={
            "1": "offline",
            "offline": "offline",
            "2": "configured",
            "configured": "configured",
        },
        default="offline",
        interactive=interactive,
    )
    preflight = _preflight(root)
    plan = install(
        root,
        source_root,
        profiles=profiles,
        components=FULL_COMPONENTS,
        kiro_target=args.kiro_target,
        flavor="full",
        apply=False,
        create_knowledge_base=False,
    )
    result: dict[str, Any] = {
        "status": "PLANNED" if args.plan_only else "PENDING",
        "baseline_version": baseline_version(source_root),
        "target": str(root),
        "flavor": "full",
        "profiles": profiles,
        "security_mode": security_mode,
        "dependency_mode": dependency_mode,
        "preflight": preflight,
        "baseline_plan": plan.as_dict(),
        "deferred_knowledge_base_creation": not (root / "knowledge-base").exists(),
        "openwiki_generation": (
            "disabled: strict-local mode"
            if security_mode == "strict-local"
            else "first-run only"
        ),
        "knowledge_generation": "optional interactive sequence after baseline setup",
    }
    if plan.conflicts:
        raise ConflictError(
            f"Baseline preview has {len(plan.conflicts)} conflict(s); review the plan."
        )
    if args.plan_only:
        return result

    if not interactive and not args.yes:
        raise ConfigurationError(
            "Non-interactive application requires --yes plus explicit security "
            "and dependency modes."
        )
    if args.json:
        raise ConfigurationError("--json is supported only with --plan-only.")
    _require_preflight(
        preflight,
        security_mode=security_mode,
        skip_runtime_sync=args.skip_runtime_sync,
        skip_openwiki_install=args.skip_openwiki_install,
        skip_openwiki_generation=args.skip_openwiki_generation,
    )
    if (
        security_mode == "kiro-approved"
        and not interactive
        and not args.skip_openwiki_generation
    ):
        raise ConfigurationError(
            "Kiro generation requires an interactive terminal for tool approvals."
        )

    changed = [item for item in plan.actions if item["action"] not in {"PRESERVE"}]
    print(f"\nTarget: {root}")
    print(f"Profiles: {', '.join(profiles)}")
    print(f"Full baseline changes: {len(changed)}")
    if preflight["dirty_worktree"]:
        print("Warning: the target worktree already has uncommitted changes.")
    if security_mode == "kiro-approved":
        print(
            "Kiro-approved mode permits Kiro's hosted model to process repository "
            "context. It is not a strict-local mode."
        )
    else:
        print(
            "Strict-local mode stages tools and configuration but does not invoke "
            "Kiro to read the repository."
        )
    if dependency_mode == "configured":
        print(
            "Configured dependency mode may contact the package registries already "
            "configured for npm and uv."
        )
    _confirm(
        "Apply the reviewed full AIDE baseline plan?",
        assume_yes=args.yes,
        interactive=interactive,
    )

    phases: dict[str, Any] = {}
    install(
        root,
        source_root,
        profiles=profiles,
        components=FULL_COMPONENTS,
        kiro_target=args.kiro_target,
        flavor="full",
        apply=True,
        create_knowledge_base=False,
    )
    phases["baseline"] = "applied"
    _write_state(root, phases)

    _prepare_runtimes(
        root,
        dependency_mode=dependency_mode,
        skip=args.skip_runtime_sync,
        phases=phases,
    )
    _ensure_openwiki(
        root,
        package=args.openwiki_package,
        dependency_mode=dependency_mode,
        skip=args.skip_openwiki_install,
        assume_yes=args.yes,
        interactive=interactive,
        phases=phases,
    )

    if shutil.which("kiro-cli"):
        _validate_agents(root)
        phases["agents"] = "validated"
        _write_state(root, phases)

    index = root / "openwiki" / "index.md"
    if security_mode == "strict-local" or args.skip_openwiki_generation:
        phases["openwiki_generation"] = "deferred"
    elif index.exists():
        phases["openwiki_generation"] = "preserved existing wiki"
    else:
        _run_kiro_prompt(root, OPENWIKI_PROMPT, agent="kiro_default")
        errors = validate_okf(root)
        if errors:
            phases["openwiki_generation"] = "incomplete; resumable state preserved"
            _write_state(root, phases)
            raise VerificationError("; ".join(errors))
        phases["openwiki_generation"] = "complete"
    _write_state(root, phases)

    install(
        root,
        source_root,
        profiles=profiles,
        components=FULL_COMPONENTS,
        kiro_target=args.kiro_target,
        flavor="full",
        apply=True,
        create_knowledge_base=True,
    )
    phases["knowledge_base"] = (
        "available" if (root / "knowledge-base").is_dir() else "failed"
    )
    _write_state(root, phases)
    if phases["knowledge_base"] == "failed":
        raise VerificationError("knowledge-base directory was not created.")

    _run_optional_knowledge_generation(
        root,
        security_mode=security_mode,
        interactive=interactive,
        phases=phases,
    )

    if shutil.which("kiro-cli"):
        _run_checked(
            "List installed Kiro agents", ["kiro-cli", "agent", "list"], cwd=root
        )
        _run_checked(
            "List installed MCP servers", ["kiro-cli", "mcp", "list"], cwd=root
        )

    result["status"] = "COMPLETE"
    result["phases"] = phases
    result["next_steps"] = [
        "Reload the Kiro IDE window.",
        "Review generated OpenWiki content before treating it as authoritative.",
        "Review any opted-in knowledge-base and project steering artifacts before "
        "treating them as authoritative.",
        "Start with openwiki/quickstart.md when OpenWiki generation completed.",
    ]
    return result


def main(
    argv: list[str] | None = None,
    *,
    source_root: Path | None = None,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    source = source_root or Path(__file__).resolve().parents[2]
    interactive = sys.stdin.isatty() and not args.json
    try:
        result = guided_install(args, source_root=source, interactive=interactive)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            if args.plan_only:
                plan = result["baseline_plan"]
                print(
                    f"READY: full guided installation for {result['target']}; "
                    f"baseline changes {plan['changed']}."
                )
                print("No files, packages, runtimes, or OpenWiki pages were changed.")
            else:
                print("\nCOMPLETE: guided AIDE installation finished.")
                for step in result["next_steps"]:
                    print(f"- {step}")
        return 0
    except AideError as exc:
        payload = {
            "status": "ERROR",
            "error": type(exc).__name__,
            "message": str(exc),
        }
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return exc.exit_code
    except (OSError, json.JSONDecodeError) as exc:
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
        return 2
