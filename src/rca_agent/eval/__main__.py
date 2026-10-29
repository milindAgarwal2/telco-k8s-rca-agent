"""CLI entrypoint: ``python -m rca_agent.eval``.

Runs the fault-injection harness, prints a summary, and writes the results
table (markdown + CSV) under ``src/rca_agent/eval/results/``. Exits non-zero if
top-2 accuracy falls below ``--min-top2`` (default 0.80) so it can gate CI.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rca_agent.eval.report import to_csv, to_markdown
from rca_agent.eval.runner import run_harness

_RESULTS_DIR = Path(__file__).parent / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rca_agent.eval",
                                     description="RCA agent fault-injection "
                                                 "accuracy harness (offline).")
    parser.add_argument("--min-top2", type=float, default=0.80,
                        help="minimum top-2 accuracy to pass (default 0.80)")
    parser.add_argument("--no-write", action="store_true",
                        help="do not write results files, just print")
    parser.add_argument("--out-dir", default=str(_RESULTS_DIR),
                        help="directory for results.md / results.csv")
    args = parser.parse_args(argv)

    report = run_harness()

    print(f"Cases: {report.total}  "
          f"Top-1: {report.top1_accuracy * 100:.0f}% ({report.top1_hits}/{report.total})  "
          f"Top-2: {report.top2_accuracy * 100:.0f}% ({report.top2_hits}/{report.total})  "
          f"Errors: {report.errors}")
    for r in report.results:
        status = "ERR " if r.error else (
            "TOP1" if r.score.top1 else ("TOP2" if r.score.top2 else "MISS"))
        print(f"  [{status}] {r.case_id:<24} rank={r.score.matched_rank} "
              f"=> {r.top_cause or '(none)'}")
        if r.error:
            print(f"         error: {r.error}")

    if not args.no_write:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.md").write_text(to_markdown(report), encoding="utf-8")
        (out / "results.csv").write_text(to_csv(report), encoding="utf-8")
        print(f"\nWrote {out / 'results.md'} and {out / 'results.csv'}")

    if report.top2_accuracy < args.min_top2:
        print(f"\nFAIL: top-2 accuracy {report.top2_accuracy * 100:.0f}% "
              f"< threshold {args.min_top2 * 100:.0f}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
