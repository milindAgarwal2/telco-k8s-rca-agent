"""Render a HarnessReport to a markdown results table and a CSV.

Kept ASCII-safe (status words, not emoji) so the output pipes cleanly through a
non-UTF-8 shell, consistent with the rest of the project.
"""
from __future__ import annotations

import csv
import io

from rca_agent.eval.runner import CaseResult, HarnessReport

_COLUMNS = ["case", "fault_type", "expected_cause", "top_hypothesis",
            "matched_rank", "top1", "top2", "error"]


def _row(r: CaseResult) -> dict:
    return {
        "case": r.case_id,
        "fault_type": r.fault_type,
        "expected_cause": r.expected,
        "top_hypothesis": r.top_cause or "(none)",
        "matched_rank": r.score.matched_rank or "-",
        "top1": "yes" if r.score.top1 else "no",
        "top2": "yes" if r.score.top2 else "no",
        "error": r.error or "",
    }


def to_markdown(report: HarnessReport) -> str:
    lines: list[str] = []
    lines.append("# RCA Agent - Fault-Injection Accuracy Results")
    lines.append("")
    lines.append("Synthetic offline harness (no cluster, no LLM). Each case "
                 "injects one known fault into a fake cluster, runs the real "
                 "extractive pipeline, and scores the ranked hypotheses. "
                 "**Accuracy metric: top-2** (the known cause is among the top "
                 "two hypotheses).")
    lines.append("")
    lines.append(f"- Cases: **{report.total}**")
    lines.append(f"- Top-1 accuracy: **{report.top1_accuracy * 100:.0f}%** "
                 f"({report.top1_hits}/{report.total})")
    lines.append(f"- Top-2 accuracy: **{report.top2_accuracy * 100:.0f}%** "
                 f"({report.top2_hits}/{report.total})")
    if report.errors:
        lines.append(f"- Errors: **{report.errors}**")
    lines.append("")
    header = ["Case", "Fault type", "Expected cause", "Top hypothesis",
              "Rank", "Top-1", "Top-2"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for r in report.results:
        row = _row(r)
        cells = [row["case"], row["fault_type"], row["expected_cause"],
                 row["top_hypothesis"], str(row["matched_rank"]),
                 row["top1"], row["top2"]]
        # escape pipes in free text
        cells = [c.replace("|", "\\|") for c in cells]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def to_csv(report: HarnessReport) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_COLUMNS)
    w.writeheader()
    for r in report.results:
        w.writerow(_row(r))
    return buf.getvalue()
