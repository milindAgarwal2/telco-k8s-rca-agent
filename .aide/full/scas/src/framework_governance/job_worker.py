from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from .jobs import JobStateWriter, read_json, scan_result_from_dict, utc_now
from .service import AssessmentCancelled, GovernanceService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detached framework assessment worker.")
    parser.add_argument("--job-directory", required=True)
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--state-file", required=True)
    return parser


def run_worker(job_directory: Path, plan_file: Path, state_file: Path) -> int:
    plan = read_json(plan_file)
    cancel_file = job_directory / "cancel.requested"
    writer = JobStateWriter(
        state_file,
        heartbeat_interval_seconds=float(
            plan.get("heartbeat_interval_seconds", 5)
        ),
    )
    writer.start()
    try:
        assessment, reports = GovernanceService().assess(
            repository=plan["repository_path"],
            config_path=plan["config_path"],
            output_directory=plan["output_directory"],
            scan_result=scan_result_from_dict(plan["scan"]),
            progress_callback=writer.handle_event,
            cancellation_check=cancel_file.exists,
        )
        writer.update(
            status="completed",
            health="healthy",
            phase="completed",
            progress_percent=100.0,
            processed_items=len(plan["scan"].get("components", [])),
            remaining_items=0,
            current_item=None,
            current_item_status="completed",
            completed_at=utc_now(),
            reports=reports,
            assessment_summary={
                "compliance_score": assessment.compliance_score(),
                "status_counts": assessment.counts(),
                "catalog_errors": len(assessment.catalog_errors),
            },
        )
        return 0
    except AssessmentCancelled:
        writer.update(
            status="cancelled",
            health="healthy",
            phase="cancelled",
            current_item_status="cancelled",
            current_item=None,
            completed_at=utc_now(),
            cancel_requested=True,
        )
        return 2
    except BaseException as exc:
        writer.update(
            status="failed",
            health="failed",
            phase="failed",
            current_item_status="failed",
            current_item=None,
            completed_at=utc_now(),
            error=f"{type(exc).__name__}: {exc}",
        )
        traceback.print_exc()
        return 1
    finally:
        writer.stop()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    exit_code = run_worker(
        Path(args.job_directory).resolve(),
        Path(args.plan_file).resolve(),
        Path(args.state_file).resolve(),
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
