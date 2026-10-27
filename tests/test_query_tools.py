"""Tests for the real read-only KubeQueryTools, using the fake kube client.

No cluster and no kubernetes package needed — the fake client (``fake_kube``)
duck-types the object model well enough for the query tools to traverse.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rca_agent.tools.query_tools import KubeQueryTools, get_query_tools
from tests import fake_kube as fk

NS = "open5gs"


def _now():
    return datetime.now(timezone.utc)


def _store() -> dict:
    """A small namespace: one healthy upf pod, one OOMKilled upf pod, events,
    logs, a recently edited configmap, and a fresh ReplicaSet (rollout).
    """
    recent = _now() - timedelta(minutes=3)
    old = _now() - timedelta(hours=2)
    return {
        "pods": [
            fk.pod("upf-7c9-aaaa", healthy=True),
            fk.pod("upf-7c9-bbbb", healthy=False, oomkilled=True, restart_count=5),
            fk.pod("smf-abc-1111", healthy=True),
        ],
        "events": [
            fk.event("upf-7c9-bbbb", "OOMKilled",
                     "Container upf was OOMKilled", last_timestamp=recent),
            fk.event("upf-7c9-bbbb", "Scheduled",
                     "pod scheduled", etype="Normal", last_timestamp=old),
            fk.event("other-pod-9999", "BackOff", "noise", last_timestamp=recent),
        ],
        "logs": {
            "upf-7c9-bbbb": {
                "previous": 'level=error msg="out of memory"\n'
                            'level=fatal msg="gtp-u alloc failed"',
                "current": 'level=info msg="starting up"',
            },
            "upf-7c9-aaaa": {"current": 'level=info msg="healthy"'},
        },
        "configmaps": [
            fk.configmap("upf-config", modified=recent),
            fk.configmap("stable-config", modified=old),
        ],
        "secrets": [],
        "pvcs": [],
        "replicasets": [
            fk.replicaset("upf-7c9", "upf", replicas=2, created=recent,
                          images=["upf:2.0"]),
        ],
        "deployments": [fk.deployment("upf", replicas=2)],
    }


def _tools(store) -> KubeQueryTools:
    return KubeQueryTools(kube_client=fk.FakeKubeClient(store))


# --- factory -----------------------------------------------------------------
def test_factory_returns_stub_when_cluster_disabled():
    from rca_agent.tools.query_tools import StubQueryTools
    assert isinstance(get_query_tools(False), StubQueryTools)


def test_factory_returns_kube_tools_when_enabled():
    tools = get_query_tools(True, kube_client=fk.FakeKubeClient(_store()))
    assert isinstance(tools, KubeQueryTools)


# --- pod_status --------------------------------------------------------------
def test_pod_status_picks_the_most_degraded_pod_for_a_workload():
    tools = _tools(_store())
    # "upf" resolves to both upf pods; the OOMKilled one should be reported.
    status = tools.pod_status("upf", NS)
    assert status["pod"] == "upf-7c9-bbbb"
    assert status["ready"] is False
    assert status["restart_count"] == 5
    assert status["last_termination_reason"] == "OOMKilled"


def test_pod_status_exact_pod_name():
    tools = _tools(_store())
    status = tools.pod_status("upf-7c9-aaaa", NS)
    assert status["pod"] == "upf-7c9-aaaa"
    assert status["ready"] is True


def test_pod_status_unknown_resource_is_graceful():
    tools = _tools(_store())
    status = tools.pod_status("does-not-exist", NS)
    assert status["phase"] == "Unknown"
    assert status["note"] == "pod not found"


def test_pod_status_strips_graph_id_prefix():
    tools = _tools(_store())
    status = tools.pod_status("service/upf", NS)  # 'service/' prefix stripped
    assert status["pod"].startswith("upf-")


# --- recent_events -----------------------------------------------------------
def test_recent_events_filters_to_resource_and_window():
    tools = _tools(_store())
    events = tools.recent_events("upf-7c9-bbbb", NS, since_minutes=30)
    reasons = [e.reason for e in events]
    # OOMKilled (recent) kept; Scheduled (2h old) dropped; other-pod noise dropped.
    assert "OOMKilled" in reasons
    assert "Scheduled" not in reasons
    assert all(e.name == "upf-7c9-bbbb" for e in events)


def test_recent_events_warning_sorts_first():
    tools = _tools(_store())
    events = tools.recent_events("upf", NS, since_minutes=30)
    assert events, "expected at least one event"
    assert events[0].event_type == "Warning"


# --- logs --------------------------------------------------------------------
def test_logs_prefers_previous_for_crashed_container_and_prefixes_pod():
    tools = _tools(_store())
    lines = tools.logs("upf-7c9-bbbb", NS, tail_lines=50)
    joined = "\n".join(lines)
    # previous logs (the crash) are returned, not the current "starting up".
    assert "out of memory" in joined
    assert "gtp-u alloc failed" in joined
    assert "[upf-7c9-bbbb/app]" in lines[0]


def test_logs_uses_current_when_no_previous():
    tools = _tools(_store())
    lines = tools.logs("upf-7c9-aaaa", NS, tail_lines=50)
    assert any("healthy" in ln for ln in lines)


# --- metrics -----------------------------------------------------------------
def test_metrics_graceful_without_prometheus_url():
    tools = _tools(_store())
    out = tools.metrics("up", NS)
    assert out["available"] is False
    assert out["result"] == []


# --- recent_changes ----------------------------------------------------------
def test_recent_changes_detects_configmap_edit_and_rollout():
    tools = _tools(_store())
    changes = tools.recent_changes(NS, since_minutes=15)
    types = {c["type"] for c in changes}
    objects = {c["object"] for c in changes}
    # The recently-edited configmap is flagged; the old one is not.
    assert "configmap_update" in types
    assert "upf-config" in objects
    assert "stable-config" not in objects
    # The fresh ReplicaSet is flagged as a rollout (attributed to its owner 'upf').
    assert "rollout" in types


def test_recent_changes_empty_when_nothing_recent():
    recent_store = _store()
    # Make every object old.
    old = _now() - timedelta(hours=5)
    recent_store["configmaps"] = [fk.configmap("upf-config", modified=old)]
    recent_store["replicasets"] = []
    recent_store["deployments"] = [fk.deployment("upf")]  # no managedFields time
    tools = _tools(recent_store)
    changes = tools.recent_changes(NS, since_minutes=15)
    assert changes == []
