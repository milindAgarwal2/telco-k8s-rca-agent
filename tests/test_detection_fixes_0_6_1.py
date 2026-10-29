"""Tests for the 0.6.1 detection fixes, reproducing the Cobra scenario where
no incidents were reported despite 12 eric-pc-sm-* pods failing readiness
probes (HTTP 500):

  Fix A — the real Unhealthy events were ~74 min old and the hard-coded 60s
          staleness cutoff dropped them all. A configurable
          event_max_age_minutes (default 90) picks them up.
  Fix B — status-based detection raises an incident for a pod that stays
          unhealthy across N graph rebuilds even with NO fresh K8s event
          (K8s had aged the events out from under the still-broken pods).
  Fix C — /debug/detection exposes the per-cycle gate counters.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rca_agent.config import Settings
from rca_agent.detection.event_watcher import EventWatcher
from rca_agent.graph.builder import GraphBuilder
from rca_agent.reasoning.flow import ReasoningFlow
from tests import fake_kube as fk


def _now():
    return datetime.now(timezone.utc)


def _store(pods, events):
    return {
        "nodes": [fk.node("worker-1")], "pods": pods, "events": events,
        "logs": {}, "configmaps": [], "secrets": [], "pvcs": [],
        "replicasets": [], "deployments": [], "services": [],
    }


def _watcher(cfg, pods, events):
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(_store(pods, events)))
    builder.rebuild()
    flow = ReasoningFlow(cfg, graph=builder.graph, builder=builder)
    return EventWatcher(cfg, builder, flow_factory=lambda: flow)


# ---- Fix A: configurable staleness window ----------------------------------

def test_stale_unhealthy_event_picked_up_within_configured_window():
    """A 74-min-old Unhealthy event (the Cobra case) is acted on when
    event_max_age_minutes is 90, but dropped when it's 60."""
    old = _now() - timedelta(minutes=74)
    pod = fk.pod("eric-pc-sm-diameter-x", node_name="worker-1", healthy=False,
                 waiting_reason=None)
    ev = [fk.event("eric-pc-sm-diameter-x", "Unhealthy",
                   "Readiness probe failed: HTTP probe failed with statuscode: 500",
                   last_timestamp=old)]

    # Window 90 min -> picked up (disable status detection to isolate Fix A).
    cfg = Settings(cluster_enabled=True, namespace="open5gs",
                   event_max_age_minutes=90, status_detection_enabled=False)
    reports = _watcher(cfg, [pod], ev).poll_once()
    assert len(reports) == 1
    assert reports[0].affected_resource == "eric-pc-sm-diameter-x"

    # Window 60 min -> the 74-min event is still too old, dropped.
    cfg2 = Settings(cluster_enabled=True, namespace="open5gs",
                    event_max_age_minutes=60, status_detection_enabled=False)
    assert _watcher(cfg2, [pod], ev).poll_once() == []


# ---- Fix B: status-based detection (no fresh event) ------------------------

def test_persistently_unhealthy_pod_raises_incident_without_any_event():
    """No events at all, but the pod is unhealthy in the graph across N
    rebuilds -> an incident is raised anyway."""
    cfg = Settings(cluster_enabled=True, namespace="open5gs",
                   status_detection_enabled=True, status_unhealthy_rebuilds=2)
    pod = fk.pod("eric-pc-sm-sgw-session-y", node_name="worker-1", healthy=False)
    w = _watcher(cfg, [pod], [])

    # First poll: streak=1 (< threshold 2) -> nothing yet.
    assert w.poll_once() == []
    # Second poll: streak=2 -> incident raised.
    reports = w.poll_once()
    assert len(reports) == 1
    assert reports[0].affected_resource == "eric-pc-sm-sgw-session-y"
    assert "PodPersistentlyUnhealthy" in reports[0].symptom
    # Third poll: already open -> not re-fired.
    assert w.poll_once() == []


def test_status_detection_disabled_raises_nothing():
    cfg = Settings(cluster_enabled=True, namespace="open5gs",
                   status_detection_enabled=False)
    pod = fk.pod("eric-pc-sm-x", node_name="worker-1", healthy=False)
    w = _watcher(cfg, [pod], [])
    assert w.poll_once() == []
    assert w.poll_once() == []


# ---- Fix C: diagnostics counters -------------------------------------------

def test_debug_detection_counters_reflect_the_cycle():
    old = _now() - timedelta(minutes=74)
    pod = fk.pod("eric-pc-sm-diameter-x", node_name="worker-1", healthy=False)
    ev = [fk.event("eric-pc-sm-diameter-x", "Unhealthy",
                   "Readiness probe failed: HTTP probe failed with statuscode: 500",
                   last_timestamp=old)]
    # Tight window so the event is counted as dropped_stale; status detection on.
    cfg = Settings(cluster_enabled=True, namespace="open5gs",
                   event_max_age_minutes=60, status_detection_enabled=True,
                   status_unhealthy_rebuilds=1)
    w = _watcher(cfg, [pod], ev)
    w.poll_once()
    d = w.last_diag
    assert d["events_seen"] == 1
    assert d["matched_fault_reason"] == 1
    assert d["dropped_stale"] == 1          # 74-min event dropped by 60-min window
    assert d["event_incidents"] == 0        # ...so no event-based incident
    assert d["status_incidents"] == 1       # but status detection caught it
    assert d["unhealthy_pods"] == 1
    assert d["events_403"] is False
