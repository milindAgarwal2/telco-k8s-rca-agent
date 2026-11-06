"""Command-line interface for the reusable AIDE baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .errors import AideError, ConfigurationError
from .hooks import dispatch
from .installer import bootstrap, install, reset, uninstall, validate_project
from .integrations import handshake, load_catalog
from .integrations import status as integration_status
from .postman import apply_readyz, verify_readyz
from .postman import inspect as inspect_postman
from .profiles import detect_profiles
from .selection import read_selection_file, selection_catalog
from .util import ensure_python_supported, find_git_root, read_json, redact
from .validation import run_validations
from .workflow import accept, approve, record_evidence, resume, start, terminate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aide", description="Reusable AIDE repository overlay"
    )
    parser.add_argument("--json", action="store_true", dest="global_json")
    sub = parser.add_subparsers(dest="command", required=True)

    install_parser = sub.add_parser("install")
    install_parser.add_argument("--target", default=".")
    install_parser.add_argument("--profile", "--profiles", action="append")
    install_parser.add_argument("--integration", "--integrations", action="append")
    install_parser.add_argument("--component", "--components", action="append")
    install_parser.add_argument(
        "--kiro-target", choices=["auto", "current", "cli2"], default="auto"
    )
    install_parser.add_argument(
        "--flavor", choices=["minimal", "full", "extended", "all"]
    )
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--json", action="store_true")
    install_parser.add_argument("--selection-file")

    selection = sub.add_parser("selection-catalog")
    selection.add_argument("--target", default=".")
    selection.add_argument("--flavor", choices=["full", "extended"], required=True)
    selection.add_argument("--json", action="store_true")

    sub.add_parser("bootstrap").add_argument("--target", default=".")
    for name in ("doctor", "status", "validate"):
        item = sub.add_parser(name)
        item.add_argument("--target", default=".")
        if name == "doctor":
            item.add_argument("--connections", action="store_true")
        item.add_argument("--json", action="store_true")

    update = sub.add_parser("update")
    update.add_argument("--target", default=".")
    update.add_argument("--plan", action="store_true")
    update.add_argument("--apply", action="store_true")
    update.add_argument("--source")
    update.add_argument("--flavor", choices=["minimal", "full", "extended", "all"])
    update.add_argument("--json", action="store_true")
    update.add_argument("--selection-file")
    removal = sub.add_parser("uninstall")
    removal.add_argument("--target", default=".")
    removal.add_argument("--plan", action="store_true")
    removal.add_argument("--apply", action="store_true")
    removal.add_argument("--json", action="store_true")
    reset_parser = sub.add_parser("reset")
    reset_parser.add_argument("--target", default=".")
    reset_parser.add_argument("--plan", action="store_true")
    reset_parser.add_argument("--apply", action="store_true")
    reset_parser.add_argument("--confirm")
    reset_parser.add_argument("--json", action="store_true")

    workflow = sub.add_parser("workflow")
    workflow_sub = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_start = workflow_sub.add_parser("start")
    workflow_start.add_argument("name")
    workflow_start.add_argument("--target", default=".")
    workflow_start.add_argument("--plan", required=True)
    workflow_start.add_argument("--scope", action="append", required=True)
    workflow_start.add_argument("--operation-target", action="append", required=True)
    workflow_resume = workflow_sub.add_parser("resume")
    workflow_resume.add_argument("run_id")
    workflow_resume.add_argument("--target", default=".")
    workflow_mark = workflow_sub.add_parser("mark")
    workflow_mark.add_argument("run_id")
    workflow_mark.add_argument(
        "--state",
        required=True,
        choices=["BLOCKED", "FAILED", "CANCELLED", "OUTCOME_UNKNOWN"],
    )
    workflow_mark.add_argument("--reason", required=True)
    workflow_mark.add_argument("--target", default=".")

    approval = sub.add_parser("approve")
    approval.add_argument("run_id")
    approval.add_argument("--target", default=".")
    approval.add_argument("--actor", required=True)
    approval.add_argument("--statement", required=True)
    acceptance = sub.add_parser("accept")
    acceptance.add_argument("run_id")
    acceptance.add_argument("--target", default=".")
    acceptance.add_argument("--actor", required=True)

    evidence = sub.add_parser("evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_record = evidence_sub.add_parser("record")
    evidence_record.add_argument("run_id")
    evidence_record.add_argument("--target", default=".")
    evidence_record.add_argument("--artifact", action="append", required=True)
    evidence_record.add_argument("--result", required=True)

    postman = sub.add_parser("postman")
    postman_sub = postman.add_subparsers(dest="postman_command", required=True)
    postman_inspect = postman_sub.add_parser("inspect")
    postman_inspect.add_argument("collection")
    postman_inspect.add_argument("--target", default=".")
    postman_apply = postman_sub.add_parser("apply-readyz")
    postman_apply.add_argument("run_id")
    postman_apply.add_argument("collection")
    postman_apply.add_argument("runbook")
    postman_apply.add_argument("--target", default=".")
    postman_verify = postman_sub.add_parser("verify-readyz")
    postman_verify.add_argument("collection")
    postman_verify.add_argument("--target", default=".")

    integrations = sub.add_parser("integration")
    integration_sub = integrations.add_subparsers(
        dest="integration_command", required=True
    )
    integration_list = integration_sub.add_parser("status")
    integration_list.add_argument("--name", action="append")
    integration_probe = integration_sub.add_parser("handshake")
    integration_probe.add_argument("name")

    hook = sub.add_parser("hook")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    hook_dispatch = hook_sub.add_parser("dispatch")
    hook_dispatch.add_argument("--name", required=True)
    hook_dispatch.add_argument("--target", default=".")
    hook_dispatch.add_argument("--payload")
    return parser


def _root(value: str) -> Path:
    return find_git_root(Path(value))


def _source(source_root: Path | None) -> Path:
    if source_root:
        return source_root.resolve(strict=True)
    return Path(__file__).resolve().parents[2]


def _split(values: list[str] | None) -> list[str] | None:
    """Accept repeated options and comma-separated portable examples."""

    if values is None:
        return None
    return [
        item.strip() for value in values for item in value.split(",") if item.strip()
    ]


def _select_install_flavor(value: str | None) -> str:
    """Resolve an explicit flavor or ask an interactive installer user."""

    if value:
        return "full" if value == "all" else value
    if not sys.stdin.isatty():
        raise ConfigurationError(
            "Non-interactive installation requires --flavor minimal, full, or extended."
        )
    print("Select AIDE baseline flavor:")
    print("  1. minimal - portable core agents, skills, hooks, and workflows")
    print("  2. full/all - every packaged agent, skill, hook, and workspace MCP")
    print("  3. extended - full workspace plus GUI-managed metrics dashboard")
    while True:
        response = input("Flavor [minimal]: ").strip().lower()
        if response in {"", "1", "minimal"}:
            return "minimal"
        if response in {"2", "full", "all"}:
            return "full"
        if response in {"3", "extended"}:
            return "extended"
        print("Enter minimal, full, extended, all, 1, 2, or 3.")


def _update_selection(
    project: dict[str, Any], requested_flavor: str | None
) -> tuple[str, list[str] | None]:
    """Resolve update flavor and remove full's implicit optional-agent selection."""

    current_flavor = project.get("flavor", "minimal")
    flavor = "full" if requested_flavor == "all" else requested_flavor
    flavor = flavor or current_flavor
    components = project.get("components")
    if (
        requested_flavor
        and current_flavor in {"full", "extended"}
        and flavor == "minimal"
    ):
        components = [item for item in (components or []) if item != "optional-agents"]
    return flavor, components


def _run(args: argparse.Namespace, source_root: Path | None) -> Any:
    source = _source(source_root)
    if args.command == "selection-catalog":
        return selection_catalog(source, _root(args.target), args.flavor)
    if args.command == "install":
        flavor = _select_install_flavor(args.flavor)
        return install(
            Path(args.target),
            source,
            profiles=_split(args.profile),
            integrations=_split(args.integration),
            components=_split(args.component),
            kiro_target=args.kiro_target,
            flavor=flavor,
            apply=not args.dry_run,
            selected_items=(
                read_selection_file(Path(args.selection_file))
                if args.selection_file
                else None
            ),
        ).as_dict()
    if args.command == "bootstrap":
        return bootstrap(Path(args.target))
    if args.command in {"doctor", "status", "validate"}:
        root = _root(args.target)
        project_path = root / ".aide" / "project.json"
        project = read_json(project_path) if project_path.exists() else {}
        if project:
            validate_project(project)
        result: dict[str, Any] = {
            "root": str(root),
            "installed": bool(project),
            "profiles": detect_profiles(root),
            "integrations": integration_status(source, project.get("integrations")),
        }
        if args.command in {"doctor", "validate"}:
            result["validation"] = run_validations(root, project.get("validation"))
        if args.command == "doctor" and args.connections:
            result["connection_checks"] = {}
            catalog = load_catalog(source)
            for name in project.get("integrations", []):
                result["connection_checks"][name] = handshake(catalog[name])
        return result
    if args.command == "update":
        if args.plan and args.apply:
            raise ConfigurationError("Choose either --plan or --apply.")
        root = _root(args.target)
        project = read_json(root / ".aide" / "project.json")
        validate_project(project)
        update_source = (
            Path(args.source).resolve(strict=True) if args.source else source
        )
        flavor, components = _update_selection(project, args.flavor)
        return install(
            root,
            update_source,
            profiles=project.get("profiles"),
            integrations=project.get("integrations"),
            components=components,
            kiro_target=project.get("kiro_target", "auto"),
            flavor=flavor,
            apply=args.apply,
            operation="update",
            selected_items=(
                read_selection_file(Path(args.selection_file))
                if args.selection_file
                else None
            ),
        ).as_dict()
    if args.command == "uninstall":
        if args.plan and args.apply:
            raise ConfigurationError("Choose either --plan or --apply.")
        return uninstall(Path(args.target), apply=args.apply).as_dict()
    if args.command == "reset":
        if args.plan and args.apply:
            raise ConfigurationError("Choose either --plan or --apply.")
        return reset(
            Path(args.target),
            apply=args.apply,
            confirmation=args.confirm,
        ).as_dict()
    if args.command == "workflow":
        root = _root(args.target)
        if args.workflow_command == "start":
            return start(root, args.name, args.plan, args.scope, args.operation_target)
        if args.workflow_command == "mark":
            return terminate(root, args.run_id, args.state, args.reason)
        return resume(root, args.run_id)
    if args.command == "approve":
        return approve(_root(args.target), args.run_id, args.actor, args.statement)
    if args.command == "accept":
        return accept(_root(args.target), args.run_id, args.actor)
    if args.command == "evidence":
        root = _root(args.target)
        result = json.loads(Path(args.result).read_text(encoding="utf-8"))
        return record_evidence(root, args.run_id, args.artifact, result)
    if args.command == "postman":
        root = _root(args.target)
        if args.postman_command == "inspect":
            return inspect_postman(root, args.collection)
        if args.postman_command == "apply-readyz":
            return apply_readyz(root, args.run_id, args.collection, args.runbook)
        return verify_readyz(root, args.collection)
    if args.command == "integration":
        if args.integration_command == "status":
            return integration_status(source, args.name)
        catalog = load_catalog(source)
        if args.name not in catalog:
            raise ConfigurationError(f"Unknown integration: {args.name}")
        return handshake(catalog[args.name])
    if args.command == "hook":
        payload_text = args.payload
        if payload_text is None and not sys.stdin.isatty():
            payload_text = sys.stdin.read().strip()
        payload = json.loads(payload_text) if payload_text else {}
        return dispatch(_root(args.target), args.name, payload)
    raise ConfigurationError(f"Unsupported command: {args.command}")


def main(argv: list[str] | None = None, source_root: Path | None = None) -> int:
    """Parse, execute, redact, and report a command."""

    ensure_python_supported()
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = redact(_run(args, source_root))
        json_mode = bool(
            getattr(args, "global_json", False) or getattr(args, "json", False)
        )
        if json_mode:
            print(json.dumps(result, indent=2, sort_keys=True))
        elif isinstance(result, dict) and "actions" in result:
            for item in result["actions"]:
                print(f"{item['action']:<9} {item['path']}")
            for conflict in result["conflicts"]:
                print(
                    f"CONFLICT  {conflict['path']}: {conflict['reason']}",
                    file=sys.stderr,
                )
            print(
                f"{result['status']}: {result['operation']} for "
                f"{result['target']}; flavor {result['flavor']}; "
                f"changes {result['changed']}"
            )
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 4 if isinstance(result, dict) and result.get("conflicts") else 0
    except AideError as exc:
        error = {"status": "ERROR", "error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error, indent=2), file=sys.stderr)
        return exc.exit_code
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "ERROR", "error": type(exc).__name__, "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
