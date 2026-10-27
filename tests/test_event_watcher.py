"""Unit tests for the automatic-detection event watcher.

Regression guard for Phase 1's "Event watcher": a fault-signal K8s event for a
pod the dependency graph already knows about must turn into an incident report
with NO human having to craft an Alertmanager payload — and the same event
must not be re-diagnosed on every poll cycle.

Also covers 0.3.4's incident correlation: the real-cluster regression where
12 pods failing identically got reported as 12 unlinked incidents (see
PLAN.md Known Issues) — ``_correlate`` must link same-signature incidents on
different resources within the correlation window, and must NOT link
different-signature ones even within the same window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rca_agent.config import Settings
from rca_agent.detection.event_watcher import EventWatcher
from rca_agent.graph.builder import GraphBuilder
from rca_agent.models.incident import Hypothesis, IncidentReport
from rca_agent.reasoning.flow import ReasoningFlow
from tests import fake_kube as fk


def _now():
    return datetime.now(timezone.utc)


def _store(events):
    return {
        "nodes": [fk.node("worker-1")],
        "pods": [
            fk.pod("upf-7c9-bbbb", node_name="worker-1", healthy=False,
                   oomkilled=True, restart_count=4,
                   owner_refs=[fk.owner("upf-7c9")]),
        ],
        "events": events,
        "logs": {},
        "configmaps": [],
        "secrets": [],
        "pvcs": [],
        "replicasets": [fk.replicaset("upf-7c9", "upf", replicas=1)],
        "deployments": [fk.deployment("upf", replicas=1)],
        "services": [],
    }


def _make_watcher(events):
    cfg = Settings(cluster_enabled=True, namespace="open5gs")
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(_store(events)))
    builder.rebuild()  # populate the graph so the watcher has nodes to scope against
    flow = ReasoningFlow(cfg, graph=builder.graph, builder=builder)
    watcher = EventWatcher(cfg, builder, flow_factory=lambda: flow)
    return watcher


def test_fault_event_on_known_node_becomes_an_incident():
    recent = _now() - timedelta(seconds=10)
    events = [fk.event("upf-7c9-bbbb", "OOMKilled",
                       "Container upf was OOMKilled", last_timestamp=recent)]
    watcher = _make_watcher(events)

    reports = watcher.poll_once()

    assert len(reports) == 1
    report = reports[0]
    assert "OOMKilled" in report.hypotheses[0].cause
    assert report.affected_resource == "upf-7c9-bbbb"
    # Stored for later retrieval via /incidents.
    assert watcher.incidents == [report]
    assert watcher.get_incident(report.incident_id) is report


def test_same_event_is_not_rediagnosed_on_the_next_poll():
    recent = _now() - timedelta(seconds=10)
    events = [fk.event("upf-7c9-bbbb", "OOMKilled",
                       "Container upf was OOMKilled", last_timestamp=recent)]
    watcher = _make_watcher(events)

    first = watcher.poll_once()
    second = watcher.poll_once()

    assert len(first) == 1
    assert second == []  # same event, same UID-equivalent key -> no duplicate
    assert len(watcher.incidents) == 1


def test_event_for_a_node_outside_the_graph_is_ignored():
    recent = _now() - timedelta(seconds=10)
    events = [fk.event("some-unrelated-pod-not-in-graph", "CrashLoopBackOff",
                       "back-off restarting failed container", last_timestamp=recent)]
    watcher = _make_watcher(events)

    reports = watcher.poll_once()

    assert reports == []
    assert watcher.incidents == []


def test_non_fault_reason_warning_event_is_ignored():
    """Conservative trigger: only the named FAULT_REASONS, not every Warning."""
    recent = _now() - timedelta(seconds=10)
    events = [fk.event("upf-7c9-bbbb", "FailedGetResourceMetrics",
                       "unable to fetch pod metrics", last_timestamp=recent)]
    watcher = _make_watcher(events)

    reports = watcher.poll_once()

    assert reports == []
    assert watcher.incidents == []


def test_stale_event_outside_the_poll_window_is_ignored():
    """An old lastTimestamp (well before the watcher started) must not flood
    the first poll with ancient, no-longer-relevant events."""
    stale = _now() - timedelta(hours=6)
    events = [fk.event("upf-7c9-bbbb", "OOMKilled",
                       "Container upf was OOMKilled", last_timestamp=stale)]
    watcher = _make_watcher(events)

    reports = watcher.poll_once()

    assert reports == []
    assert watcher.incidents == []


# ---------------------------------------------------------------------------
# Incident correlation (0.3.4) — regression guard for the real eric-pc-sm-*
# outage: 12 pods failing identically must come out LINKED, not as 12
# unrelated-looking incidents.
# ---------------------------------------------------------------------------
def _multi_store(specs: list[dict]):
    """``specs``: ``[{"name", "reason", "message", "oomkilled"?}, ...]``."""
    recent = _now() - timedelta(seconds=5)
    pods = [
        fk.pod(s["name"], node_name="worker-1", healthy=False,
               oomkilled=s.get("oomkilled", False))
        for s in specs
    ]
    events = [
        fk.event(s["name"], s["reason"], s["message"], last_timestamp=recent)
        for s in specs
    ]
    return {
        "nodes": [fk.node("worker-1")], "pods": pods, "events": events,
        "logs": {}, "configmaps": [], "secrets": [], "pvcs": [],
        "replicasets": [], "deployments": [], "services": [],
    }


def _make_multi_watcher(specs: list[dict]):
    cfg = Settings(cluster_enabled=True, namespace="open5gs")
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(_multi_store(specs)))
    builder.rebuild()
    flow = ReasoningFlow(cfg, graph=builder.graph, builder=builder)
    return EventWatcher(cfg, builder, flow_factory=lambda: flow)


def test_correlates_incidents_sharing_identical_signature_on_different_resources():
    """The eric-pc-sm-* regression: 3 different pods, identical probe-failure
    text, must come out all linked to each other with a shared-pattern note —
    not as 3 isolated incidents."""
    msg = "Readiness probe failed: HTTP probe failed with statuscode: 500"
    specs = [
        {"name": "sm-diameter-a", "reason": "Unhealthy", "message": msg},
        {"name": "sm-sgw-session-b", "reason": "Unhealthy", "message": msg},
        {"name": "sm-udp-forwarder-c", "reason": "Unhealthy", "message": msg},
    ]
    watcher = _make_multi_watcher(specs)

    reports = watcher.poll_once()

    assert len(reports) == 3
    by_resource = {r.affected_resource: r for r in reports}
    all_ids = {r.incident_id for r in reports}

    for name, report in by_resource.items():
        others = all_ids - {report.incident_id}
        assert set(report.related_incidents) == others
        note = next((s for s in report.suggested_next_steps
                    if s.startswith("Correlated:")), None)
        assert note is not None, f"expected a correlation note on {name}"
        assert "2 other resource(s)" in note
        for other_name in by_resource:
            if other_name != name:
                assert other_name in note


def test_does_not_correlate_incidents_with_different_failure_signatures():
    """An OOMKilled pod and a probe-failing pod must NOT be linked just
    because they happened in the same window — different signature."""
    specs = [
        {"name": "sm-diameter-a", "reason": "Unhealthy",
         "message": "Readiness probe failed: HTTP probe failed with statuscode: 500"},
        {"name": "sm-other-b", "reason": "OOMKilled",
         "message": "Container was OOMKilled", "oomkilled": True},
    ]
    watcher = _make_multi_watcher(specs)

    reports = watcher.poll_once()

    assert len(reports) == 2
    for r in reports:
        assert r.related_incidents == []
        assert not any(s.startswith("Correlated:") for s in r.suggested_next_steps)


def test_manually_posted_incident_joins_the_same_correlation_pool():
    """record_external_incident (the webhook path) must correlate against
    incidents already in the pool, proving both routes share one timeline."""
    watcher = _make_multi_watcher([])

    def _synthetic_report(resource: str) -> IncidentReport:
        cause = f"{resource} failing health probe (HTTP probe failed with statuscode: 500)"
        return IncidentReport(
            symptom=f"PodUnhealthy on {resource}",
            affected_resource=resource,
            namespace="open5gs",
            hypotheses=[Hypothesis(cause=cause, confidence=0.5,
                                   evidence_chain=[f"symptom: PodUnhealthy on {resource}"])],
        )

    first = _synthetic_report("sm-diameter-a")
    second = _synthetic_report("sm-sgw-session-b")

    watcher.record_external_incident(first)
    watcher.record_external_incident(second)

    assert second.related_incidents == [first.incident_id]
    assert first.related_incidents == [second.incident_id]
    assert any(s.startswith("Correlated:") for s in first.suggested_next_steps)
    assert any(s.startswith("Correlated:") for s in second.suggested_next_steps)
