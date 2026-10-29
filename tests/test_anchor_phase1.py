"""Phase 1 tests for the service-anchored incident model (0.7.0):
anchor resolution (service > workload > pod) and anchor dedup in detection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rca_agent.config import Settings
from rca_agent.detection.event_watcher import EventWatcher
from rca_agent.graph.builder import GraphBuilder
from rca_agent.graph.dependency_graph import build_demo_graph
from rca_agent.reasoning.flow import ReasoningFlow
from tests import fake_kube as fk


def _now():
    return datetime.now(timezone.utc)


# ---- anchor resolution -----------------------------------------------------

def test_anchor_of_prefers_service():
    g = build_demo_graph()
    # demo: service/upf selects upf-0/1/2
    a = g.anchor_of("upf-1")
    assert a["kind"] == "service"
    assert a["id"] == "service/upf"
    assert a["display"] == "upf"


def test_pods_of_anchor_returns_selected_pods():
    g = build_demo_graph()
    pods = set(g.pods_of_anchor("service/upf"))
    assert pods == {"upf-0", "upf-1", "upf-2"}


def test_anchor_falls_back_to_workload_then_pod():
    g = build_demo_graph()
    # Remove the service's selects edges so there's no fronting service;
    # anchor should fall back to the workload "upf".
    for u, v, k in list(g.graph.out_edges("service/upf", keys=True)):
        g.graph.remove_edge(u, v, k)
    a = g.anchor_of("upf-1")
    assert a["kind"] in ("deployment",)
    assert a["display"] == "upf"


# ---- anchor dedup in detection ---------------------------------------------

def _multi_pod_store(pod_names, reason, msg):
    recent = _now() - timedelta(seconds=5)
    pods = [fk.pod(n, node_name="worker-1", healthy=False) for n in pod_names]
    # One Service selecting all of them -> they share an anchor.
    svc = fk.service("eric-pc-sm", selector={"app": "sm"})
    for p in pods:
        p.metadata.labels = {"app": "sm"}
    events = [fk.event(n, reason, msg, last_timestamp=recent) for n in pod_names]
    return {
        "nodes": [fk.node("worker-1")], "pods": pods, "events": events,
        "logs": {}, "configmaps": [], "secrets": [], "pvcs": [],
        "replicasets": [], "deployments": [], "services": [svc],
    }


def test_sibling_pods_sharing_an_anchor_dedup_to_one_incident():
    """12-pods-one-outage: sibling pods behind one Service, failing identically,
    produce ONE anchor incident with all pods listed — not N incidents."""
    names = [f"eric-pc-sm-{i}" for i in range(5)]
    msg = "Readiness probe failed: HTTP probe failed with statuscode: 500"
    store = _multi_pod_store(names, "Unhealthy", msg)
    cfg = Settings(cluster_enabled=True, namespace="open5gs",
                   status_detection_enabled=False)
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(store))
    builder.rebuild()
    flow = ReasoningFlow(cfg, graph=builder.graph, builder=builder)
    watcher = EventWatcher(cfg, builder, flow_factory=lambda: flow)

    reports = watcher.poll_once()

    # Exactly one incident, anchored on the service, with all 5 pods merged in.
    assert len(reports) == 1
    inc = reports[0]
    assert inc.anchor_kind == "service"
    assert inc.affected_anchor == "service/eric-pc-sm"
    assert set(inc.affected_pods) == set(names)
    assert len(watcher.incidents) == 1
