"""Tests for the per-incident RCA PPTX generator (webhook/pptx_report.py)."""
from __future__ import annotations

import io

import pytest

from rca_agent.config import Settings
from rca_agent.graph.dependency_graph import build_demo_graph
from rca_agent.models.alert import Alert
from rca_agent.reasoning.flow import ReasoningFlow
from rca_agent.webhook import pptx_report

pytestmark = pytest.mark.skipif(
    not pptx_report.pptx_available(), reason="python-pptx not installed")


def _sample_report():
    settings = Settings(cluster_enabled=False, reasoning_mode="extractive")
    flow = ReasoningFlow(settings, graph=build_demo_graph())
    alert = Alert(labels={"alertname": "PodOOM", "namespace": "open5gs", "pod": "upf-1",
                          "severity": "critical"},
                  annotations={"description": "OOMKilled"})
    return flow.run(alert)


def test_build_incident_pptx_returns_openable_deck():
    from pptx import Presentation

    report = _sample_report()
    data = pptx_report.build_incident_pptx(report, owners={"workload": "upf", "service": "upf"})
    assert isinstance(data, bytes) and len(data) > 5000

    prs = Presentation(io.BytesIO(data))
    # Three slides: problem definition, sequence of events, analysis.
    assert len(prs.slides) == 3

    all_text = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                all_text.append(shape.text_frame.text)
    joined = "\n".join(all_text)
    assert "RCA problem definition" in joined
    assert report.affected_resource in joined
    assert "sequence of events" in joined.lower()
    assert "ranked root-cause hypotheses" in joined.lower()


def test_build_incident_pptx_without_owners():
    report = _sample_report()
    data = pptx_report.build_incident_pptx(report)  # owners=None
    assert isinstance(data, bytes) and len(data) > 5000
