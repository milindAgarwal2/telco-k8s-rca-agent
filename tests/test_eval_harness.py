"""Tests for the fault-injection accuracy harness (assessment point #9).

Guards the headline metric (top-2 accuracy) against regressions and checks the
harness plumbing (every case runs without error and the report renders).
"""
from __future__ import annotations

from rca_agent.eval.cases import FAULT_LIBRARY
from rca_agent.eval.report import to_csv, to_markdown
from rca_agent.eval.runner import run_case, run_harness

# The committed baseline is 100% top-2 (8/8). Assert a conservative floor so a
# genuine regression fails CI without being brittle to a single hard case.
_MIN_TOP2 = 0.80


def test_harness_runs_all_cases_without_error():
    report = run_harness()
    assert report.total == len(FAULT_LIBRARY)
    assert report.errors == 0, [r.case_id for r in report.results if r.error]


def test_top2_accuracy_meets_threshold():
    report = run_harness()
    assert report.top2_accuracy >= _MIN_TOP2, (
        f"top-2 accuracy regressed to {report.top2_accuracy:.0%}; "
        f"misses={[r.case_id for r in report.results if not r.score.top2]}")


def test_every_case_produces_at_least_one_hypothesis():
    for case in FAULT_LIBRARY:
        result = run_case(case)
        assert result.error is None, f"{case.id}: {result.error}"
        assert result.score.n_hypotheses >= 1, f"{case.id}: no hypotheses"


def test_oomkilled_case_is_top1():
    """A clear single OOMKilled fault should be the #1 hypothesis — the
    strongest possible signal, a sanity anchor for the harness."""
    case = next(c for c in FAULT_LIBRARY if c.id == "oomkilled")
    result = run_case(case)
    assert result.score.top1, result.top_cause


def test_unhealthy_upstream_cascade_is_found():
    """The dependency-graph capability (#4): a cascade from an unhealthy
    upstream the pod CALLS must be surfaced within top-2."""
    case = next(c for c in FAULT_LIBRARY if c.id == "unhealthy_upstream")
    result = run_case(case)
    assert result.score.top2, result.top_cause


def test_report_renders_markdown_and_csv():
    report = run_harness()
    md = to_markdown(report)
    assert "Top-2 accuracy" in md and "| Case |" in md
    csv_text = to_csv(report)
    assert csv_text.splitlines()[0].startswith("case,fault_type")
    assert len(csv_text.splitlines()) == report.total + 1  # header + one per case


def test_results_are_ascii_safe():
    """Markdown/CSV must pipe cleanly through a non-UTF-8 shell."""
    report = run_harness()
    for text in (to_markdown(report), to_csv(report)):
        assert all(ord(c) < 128 for c in text)
