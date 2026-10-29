"""Tests for incident capture (the labelable JSONL data for later precision/
recall work)."""
from __future__ import annotations

from rca_agent.config import Settings
from rca_agent.eval.capture import (
    IncidentCaptureWriter,
    build_record,
    load_records,
)
from rca_agent.models.incident import Hypothesis, IncidentReport


def _report() -> IncidentReport:
    return IncidentReport(
        symptom="PodOOMKilled on upf-0",
        affected_resource="upf-0",
        affected_anchor="service/upf",
        anchor_kind="service",
        affected_pods=["upf-0"],
        namespace="open5gs",
        hypotheses=[Hypothesis(cause="upf-0 OOMKilled", confidence=0.9)],
    )


def test_capture_disabled_by_default_is_noop():
    w = IncidentCaptureWriter(None)
    assert w.enabled is False
    assert w.record(_report(), source="event_watcher") is False


def test_capture_writes_wellformed_record(tmp_path):
    path = str(tmp_path / "incidents.jsonl")
    w = IncidentCaptureWriter(path, include_graph=False)
    assert w.record(_report(), source="event_watcher") is True
    recs = load_records(path)
    assert len(recs) == 1
    r = recs[0]
    assert r["schema_version"] == "1"
    assert r["source"] == "event_watcher"
    assert set(r.keys()) >= {"input", "output", "labels"}
    assert r["input"]["affected_resource"] == "upf-0"
    assert r["output"]["hypotheses"][0]["cause"] == "upf-0 OOMKilled"
    # labels start EMPTY and unlabeled
    assert r["labels"]["status"] == "unlabeled"
    assert r["labels"]["gold_causes"] == []
    assert r["labels"]["is_real_incident"] is None


def test_capture_redacts_log_bodies():
    from rca_agent.models.incident import Citation, Evidence
    rep = _report()
    rep.evidence = [Evidence(category="log", summary="secret-token=abc123",
                             resource="upf-0",
                             citations=[Citation(kind="log", source="upf-0",
                                                 detail="secret-token=abc123")])]
    rec = build_record(rep, source="webhook", redact_logs=True, include_graph=False)
    log_ev = next(e for e in rec["input"]["evidence"] if e["category"] == "log")
    assert "abc123" not in log_ev["summary"]
    assert log_ev["summary"] == "<redacted log line>"


def test_capture_rolling_cap(tmp_path):
    path = str(tmp_path / "incidents.jsonl")
    w = IncidentCaptureWriter(path, include_graph=False, max_records=3)
    for _ in range(5):
        w.record(_report(), source="event_watcher")
    assert len(load_records(path)) == 3


def test_capture_never_raises_on_bad_path():
    # a path under a file (not a dir) should fail to write but not raise
    w = IncidentCaptureWriter("/dev/null/nope/incidents.jsonl", include_graph=False)
    assert w.record(_report(), source="event_watcher") is False


def test_event_watcher_captures_on_store(tmp_path):
    """Integration: an incident recorded through EventWatcher is captured when
    the path is configured, with the right source label."""
    from rca_agent.detection.event_watcher import EventWatcher
    from rca_agent.graph.builder import GraphBuilder

    path = str(tmp_path / "incidents.jsonl")
    cfg = Settings(incident_capture_path=path, incident_capture_include_graph=False)
    builder = GraphBuilder(cfg)
    builder.rebuild()
    ew = EventWatcher(cfg, builder, flow_factory=lambda: None)
    assert ew.capture.enabled is True

    ew.record_external_incident(_report())  # webhook path
    recs = load_records(path)
    assert len(recs) == 1
    assert recs[0]["source"] == "webhook"
