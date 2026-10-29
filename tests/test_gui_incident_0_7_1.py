"""Tests for the 0.7.1-0.7.3 GUI/incident enhancements:

- 0.7.1: graph node picker by kind (node/service/pod) + searchable UI partial.
- 0.7.2: event evidence carries a (displayed) timestamp, ASCII-safe.
- 0.7.3: incidents go active -> inactive under STRICT recovery (all affected
  pods healthy), and the API/UI segregate active vs inactive, newest first.
"""
from __future__ import annotations

import sys

from rca_agent.config import Settings
from rca_agent.detection.event_watcher import EventWatcher
from rca_agent.graph.builder import GraphBuilder
from rca_agent.graph.dependency_graph import Health, build_demo_graph
from rca_agent.models.incident import IncidentReport
from rca_agent.reasoning.flow import ReasoningFlow

# ---- 0.7.1: node picker by kind --------------------------------------------

def test_node_summaries_filters_by_kind():
    g = build_demo_graph()
    pods = g.node_summaries(kind="pod")
    svcs = g.node_summaries(kind="service")
    nodes = g.node_summaries(kind="node")
    assert len(pods) == 3 and all(n["kind"] == "pod" for n in pods)
    assert len(svcs) == 1 and svcs[0]["kind"] == "service"
    assert len(nodes) == 2 and all(n["kind"] == "node" for n in nodes)
    # rows carry id/display/health/kind
    assert {"id", "display", "health", "kind"} <= set(pods[0])


def test_node_summaries_none_returns_all_nodes():
    g = build_demo_graph()
    assert len(g.node_summaries(kind=None)) == g.stats()["nodes"]


def test_pods_delegates_to_node_summaries():
    g = build_demo_graph()
    assert g.pods() == g.node_summaries(kind="pod")


def test_graph_nodes_endpoint_per_kind_and_bad_kind():
    from fastapi.testclient import TestClient

    import rca_agent.webhook.app as appinst  # NOTE: binds to FastAPI instance
    client = TestClient(appinst)  # appinst IS the app object
    for kind, expected_kind in (("pod", "pod"), ("service", "service"), ("node", "node")):
        r = client.get("/graph/nodes", params={"kind": kind})
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == kind
        assert all(n["kind"] == expected_kind for n in body["nodes"])
    # configmap is a real kind but NOT a picker option -> 400
    assert client.get("/graph/nodes", params={"kind": "configmap"}).status_code == 400


def test_ui_graph_picker_partial_renders_datalist_and_map():
    from fastapi.testclient import TestClient

    import rca_agent.webhook.app as appinst
    client = TestClient(appinst)
    r = client.get("/ui/graph/nodes", params={"kind": "service"})
    assert r.status_code == 200
    assert "node-options" in r.text  # datalist
    assert "__nodeMap" in r.text     # display->id map


def test_graph_view_accepts_slash_in_node_id():
    """Regression: service/node ids contain a '/' (e.g. 'service/upf'); the
    /graph/view/{node_id:path} route must match them (was a 404 before the
    :path converter fix)."""
    from fastapi.testclient import TestClient

    import rca_agent.webhook.app as appinst
    client = TestClient(appinst)
    # real slash id present in the demo graph
    assert client.get("/graph/view/service/upf",
                      params={"with_pod_filter": False}).status_code == 200
    # a slash id that does not exist still 404s (route matched, node missing)
    assert client.get("/graph/view/service/nope").status_code == 404
    # bare (slashless) ids still work
    assert client.get("/graph/view/upf-0").status_code == 200


def test_picker_option_values_are_emoji_free_for_typeahead():
    """Regression: datalist option values must be the clean name (no leading
    health emoji), or browser typeahead can't match what the user types."""
    from fastapi.testclient import TestClient

    import rca_agent.webhook.app as appinst
    client = TestClient(appinst)
    html = client.get("/ui/graph/nodes", params={"kind": "service"}).text
    import re
    for val in re.findall(r'<option value="([^"]*)"', html):
        assert all(ord(c) < 128 for c in val), f"option value not ASCII/clean: {val!r}"


# ---- 0.7.2: event evidence timestamps --------------------------------------

def test_event_evidence_has_timestamp_prefix_and_field():
    cfg = Settings()  # extractive/stub, no cluster
    builder = GraphBuilder(cfg)
    builder.rebuild()
    flow = ReasoningFlow(cfg, graph=builder.graph, builder=builder)
    from rca_agent.models.alert import Alert

    report = flow.run(Alert(name="PodUnhealthy", status="firing",
                            labels={"pod": "upf-0"}, annotations={}))
    events = [e for e in report.evidence
              if e.category == "event" and e.timestamp is not None]
    assert events, "expected at least one event evidence with a timestamp"
    for e in events:
        # summary is prefixed with the time in brackets
        assert e.summary.startswith("[") and "]" in e.summary
        # and the whole report stays ASCII-safe (RHEL non-UTF-8 shell)
    blob = report.model_dump_json()
    assert all(ord(c) < 128 for c in blob), "report must be ASCII-safe"


# ---- 0.7.3: active/inactive strict recovery --------------------------------

def _two_pod_incident(graph) -> tuple[IncidentReport, str, str]:
    pods = [p["id"] for p in graph.pods()]
    p1, p2 = pods[0], pods[1]
    graph.set_health_state(p1, Health.down, "OOMKilled")
    graph.set_health_state(p2, Health.down, "OOMKilled")
    inc = IncidentReport(symptom="two pods down", affected_resource=p1,
                         affected_anchor="service/upf", anchor_kind="service",
                         affected_pods=[p1, p2])
    return inc, p1, p2


def _watcher_with(graph):
    cfg = Settings()
    builder = GraphBuilder(cfg)
    builder._graph = graph  # inject the graph we mutate
    flow = ReasoningFlow(cfg, graph=graph, builder=builder)
    return EventWatcher(cfg, builder, flow_factory=lambda: flow)


def test_incident_defaults_to_active():
    assert IncidentReport(symptom="x").status == "active"


def test_strict_recovery_stays_active_until_all_pods_healthy():
    g = build_demo_graph()
    ew = _watcher_with(g)
    inc, p1, p2 = _two_pod_incident(g)
    ew._store(inc)

    # Only one pod recovers -> STILL active.
    g.set_health_state(p1, Health.healthy, "")
    assert ew.reconcile_status(g) == 0
    assert inc.status == "active"
    assert inc.resolved_at is None

    # Both healthy -> flips inactive with a resolved_at.
    g.set_health_state(p2, Health.healthy, "")
    assert ew.reconcile_status(g) == 1
    assert inc.status == "inactive"
    assert inc.resolved_at is not None


def test_incidents_api_segregates_by_status_newest_first():
    from fastapi.testclient import TestClient

    import rca_agent.webhook.app as appinst
    ewmod = sys.modules["rca_agent.webhook.app"]
    ew = ewmod._event_watcher
    g = ewmod._graph_builder.graph

    ew.incidents.clear()
    inc, p1, p2 = _two_pod_incident(g)
    ew._store(inc)
    # recover both and reconcile -> inactive
    g.set_health_state(p1, Health.healthy, "")
    g.set_health_state(p2, Health.healthy, "")
    ew.reconcile_status(g)

    client = TestClient(appinst)
    assert client.get("/incidents", params={"status": "active"}).json()["count"] == 0
    assert client.get("/incidents", params={"status": "inactive"}).json()["count"] == 1
    assert client.get("/incidents", params={"status": "all"}).json()["count"] == 1
    assert client.get("/incidents", params={"status": "bogus"}).status_code == 400
    ew.incidents.clear()


def test_ui_incident_table_status_filter_and_toggle():
    from fastapi.testclient import TestClient

    import rca_agent.webhook.app as appinst
    client = TestClient(appinst)
    # toggle present on the incidents tab
    assert "inc-status" in client.get("/ui/tab/incidents").text
    # table accepts a status param
    assert client.get("/ui/incidents/table", params={"status": "inactive"}).status_code == 200
