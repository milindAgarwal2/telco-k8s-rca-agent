"""PPTX rendering test for the potential-alarms candidate block (R6 AC4).

Mirrors ``test_pptx_report.py`` in style: build a report, render the deck with
``pptx_report.build_incident_pptx``, open it with python-pptx, and assert over
the concatenated slide text. Scoped to the slide-3 candidate-alarm block added
in task 11.1 of the potential-alarms spec.

AC 6.4: the generated PPTX includes every Candidate_Alarm from a mapped
Potential_Alarms result, each paired with its Source_Citation value. The block
also suppresses candidates whose ``source_citation`` is empty, mirroring the UI.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms
from rca_agent.models.incident import Hypothesis, IncidentReport

# Import pptx_report by file path rather than via ``from rca_agent.webhook
# import pptx_report``. Importing the submodule would execute
# ``rca_agent/webhook/__init__.py`` -> ``app`` -> ``store/incident_store`` ->
# ``psycopg``, a pre-existing unrelated gap in this environment. pptx_report.py
# itself only needs stdlib + a lazy ``pptx`` import, so loading it in isolation
# exercises the candidate-alarm block under test without the package side
# effects.
_PPTX_PATH = (
    Path(__file__).resolve().parents[1]
    / "src" / "rca_agent" / "webhook" / "pptx_report.py"
)
_spec = importlib.util.spec_from_file_location("rca_pptx_report_isolated", _PPTX_PATH)
pptx_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pptx_report)

pytestmark = pytest.mark.skipif(
    not pptx_report.pptx_available(), reason="python-pptx not installed")


def _deck_text(report: IncidentReport) -> str:
    """Render the report and return the concatenated text of every slide shape."""
    data = pptx_report.build_incident_pptx(report)
    assert isinstance(data, bytes) and len(data) > 5000

    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
    return "\n".join(texts)


def _report_with_alarms(alarms: list[CandidateAlarm]) -> IncidentReport:
    return IncidentReport(
        symptom="KubePodNotReady on upf-1",
        affected_resource="upf-1",
        namespace="open5gs",
        hypotheses=[Hypothesis(cause="UPF OOMKilled", confidence=0.8)],
        potential_alarms=PotentialAlarms(pod="upf-1", mapped=True, alarms=alarms),
    )


def test_pptx_pairs_every_candidate_with_its_source_citation():
    """Every candidate alarm appears in the deck paired with its citation."""
    alarms = [
        CandidateAlarm(alarm_name="UPF-PodDown", source_citation="SON doc p.12"),
        CandidateAlarm(alarm_name="UPF-HighMem", source_citation="Runbook §4.3"),
        CandidateAlarm(alarm_name="PFCP-LinkLoss", source_citation="Alarm ref AR-7"),
    ]
    text = _deck_text(_report_with_alarms(alarms))

    # The candidate section is labelled and explicitly scoped to candidates.
    assert "Potential Alarms (candidates)" in text
    # Never presented as confirmed/active alarms.
    assert "confirmed" not in text.lower()
    assert "active" not in text.lower()

    # Each candidate is present AND paired with its own source citation.
    for a in alarms:
        assert a.alarm_name in text
        assert a.source_citation in text
        assert f"{a.alarm_name} — {a.source_citation}" in text


def test_pptx_suppresses_candidate_with_empty_citation():
    """A candidate lacking a source citation is omitted from the deck, while
    the cited candidates still render (consistent with the UI, R6 AC4)."""
    alarms = [
        CandidateAlarm(alarm_name="UPF-PodDown", source_citation="SON doc p.12"),
        CandidateAlarm(alarm_name="UPF-NoCitation", source_citation=""),
    ]
    text = _deck_text(_report_with_alarms(alarms))

    assert "Potential Alarms (candidates)" in text
    assert "UPF-PodDown" in text
    assert "SON doc p.12" in text
    # The uncited candidate is suppressed entirely.
    assert "UPF-NoCitation" not in text
