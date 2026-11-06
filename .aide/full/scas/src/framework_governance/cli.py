from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .jobs import JobManager, TERMINAL_STATUSES
from .service import GovernanceService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="framework-governance",
        description="Scan repositories and assess frameworks with SCAS Search 3PP.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Generate a local component inventory.")
    scan.add_argument("--repo", default=".", help="Repository directory.")
    scan.add_argument("--config", help="Governance JSON or YAML configuration.")
    scan.add_argument("--output", help="Optional inventory JSON path.")

    assess = subparsers.add_parser("assess", help="Run the complete SCAS assessment.")
    assess.add_argument("--repo", default=".", help="Repository directory.")
    assess.add_argument("--config", required=True, help="Governance JSON or YAML configuration.")
    assess.add_argument("--output", default="reports", help="Report output directory.")

    check = subparsers.add_parser("catalog-check", help="Check one component.")
    check.add_argument("--name", required=True)
    check.add_argument("--version")
    check.add_argument("--ecosystem", default="unknown")
    check.add_argument("--config", required=True)

    start_job = subparsers.add_parser(
        "start-job", help="Start a durable background assessment."
    )
    start_job.add_argument("--repo", default=".")
    start_job.add_argument("--config", required=True)
    start_job.add_argument("--output", default="reports")

    job_status = subparsers.add_parser(
        "job-status", help="Show or continuously watch a durable assessment."
    )
    job_status.add_argument("--job-id", required=True)
    job_status.add_argument("--watch", action="store_true")
    job_status.add_argument("--interval", type=float, default=2.0)
    job_status.add_argument("--full", action="store_true")

    list_jobs = subparsers.add_parser("list-jobs", help="List recent jobs.")
    list_jobs.add_argument("--limit", type=int, default=20)

    cancel_job = subparsers.add_parser("cancel-job", help="Cancel a running job.")
    cancel_job.add_argument("--job-id", required=True)

    subparsers.add_parser("serve-mcp", help="Start the MCP stdio server.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    service = GovernanceService()
    try:
        if args.command == "scan":
            result = service.scan(args.repo, args.config)
            payload = json.dumps(result.to_dict(), indent=2)
            if args.output:
                output = Path(args.output).resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(payload, encoding="utf-8")
                print(output)
            else:
                print(payload)
        elif args.command == "assess":
            assessment, reports = service.assess(args.repo, args.config, args.output)
            print(json.dumps({
                "compliance_score": assessment.compliance_score(),
                "status_counts": assessment.counts(),
                "reports": reports,
            }, indent=2))
        elif args.command == "catalog-check":
            result = service.check_component(
                {"name": args.name, "version": args.version, "ecosystem": args.ecosystem},
                args.config,
            )
            print(json.dumps(result, indent=2))
        elif args.command == "start-job":
            result = JobManager().start_job(args.repo, args.config, args.output)
            print(json.dumps(result, indent=2))
        elif args.command == "job-status":
            manager = JobManager()
            if not args.watch:
                result = manager.get_status(args.job_id)
                print(json.dumps(result, indent=2) if args.full else result["summary"])
            else:
                last_revision = -1
                while True:
                    result = manager.get_status(args.job_id)
                    revision = int(result.get("revision", 0))
                    if revision != last_revision:
                        _print_live_status(result)
                        last_revision = revision
                    if result.get("status") in TERMINAL_STATUSES:
                        print()
                        if result.get("reports"):
                            print(json.dumps({"reports": result["reports"]}, indent=2))
                        break
                    time.sleep(max(0.5, args.interval))
        elif args.command == "list-jobs":
            print(json.dumps(JobManager().list_jobs(args.limit), indent=2))
        elif args.command == "cancel-job":
            print(json.dumps(JobManager().cancel_job(args.job_id), indent=2))
        elif args.command == "serve-mcp":
            from .mcp_server import main as serve
            serve()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _print_live_status(state: dict) -> None:
    summary = str(state.get("summary", ""))
    counts = state.get("status_counts", {})
    count_text = " ".join(
        f"{name[0].upper()}:{counts.get(name, 0)}"
        for name in ("green", "amber", "yellow", "red", "grey")
    )
    line = f"{summary} | {count_text}"
    terminal_width = 180
    sys.stdout.write("\r" + line[:terminal_width].ljust(terminal_width))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
