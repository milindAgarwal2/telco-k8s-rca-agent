"""Tests for the 0.5.1 fixes: graph node/edge breakdown, change-actor
classification, and change attribution flowing into incident evidence."""
from __future__ import annotations

from rca_agent.graph.dependency_graph import build_demo_graph
from rca_agent.tools.query_tools import _classify_actor

# ---- Req 1: node/edge breakdown --------------------------------------------

def test_stats_includes_node_breakdown_by_kind():
    g = build_demo_graph()
    stats = g.stats()
    assert "by_kind" in stats
    bk = stats["by_kind"]
    # demo graph: 3 pods, 1 service, 1 configmap, 1 secret, 1 pvc,
    # 1 deployment, 1 replicaset, 2 worker nodes.
    assert bk["pod"] == 3
    assert bk["service"] == 1
    assert bk["configmap"] == 1
    assert bk["secret"] == 1
    assert bk["node"] == 2
    assert sum(bk.values()) == stats["nodes"]


def test_stats_includes_edge_breakdown_by_kind():
    g = build_demo_graph()
    stats = g.stats()
    assert "edges_by_kind" in stats
    assert sum(stats["edges_by_kind"].values()) == stats["edges"]


# ---- Req 3: actor classification -------------------------------------------

def test_classify_actor_human_tools():
    assert _classify_actor("kubectl-edit") == ("human (kubectl)", False)
    assert _classify_actor("kubectl-client-side-apply") == ("human (kubectl)", False)
    assert _classify_actor("oc") == ("human (oc)", False)


def test_classify_actor_automation():
    assert _classify_actor("helm") == ("Helm", True)
    assert _classify_actor("argocd-application-controller") == ("GitOps (Argo CD)", True)
    assert _classify_actor("flux")[1] is True
    assert _classify_actor("some-operator")[1] is True
    assert _classify_actor("my-controller")[1] is True


def test_classify_actor_unknown_shown_verbatim():
    label, auto = _classify_actor("weird-manager-xyz")
    assert label == "weird-manager-xyz"
    assert auto is None
    assert _classify_actor(None) == ("unknown", None)


# ---- Req 3: attribution reaches the incident evidence ----------------------

def test_change_attribution_in_evidence():
    """The stub recent_changes carries a kubectl actor; it should surface in
    the change evidence summary and citation."""
    from rca_agent.config import Settings
    from rca_agent.models.alert import Alert
    from rca_agent.reasoning.flow import ReasoningFlow

    settings = Settings(cluster_enabled=False, reasoning_mode="extractive")
    flow = ReasoningFlow(settings, graph=build_demo_graph())
    alert = Alert(labels={"alertname": "PodOOM", "namespace": "open5gs", "pod": "upf-1"},
                  annotations={"description": "OOMKilled"})
    report = flow.run(alert)

    change_cits = [c for h in report.hypotheses for c in h.citations if c.kind == "change"]
    change_ev = [e for e in report.evidence if e.category == "change"]
    # The demo/stub change is attributed to kubectl-edit (human).
    assert any(c.actor == "kubectl-edit" and c.is_automation is False
               for c in change_cits), "expected kubectl actor on a change citation"
    assert any("kubectl-edit" in e.summary for e in change_ev)


# ---- 0.5.2: owners() + blast radius / upstream on the report --------------

def test_owners_resolves_workload_and_service():
    g = build_demo_graph()
    o = g.owners("upf-1")
    # demo: upf-1 is managed (via replicaset upf-7c9) by deployment "upf",
    # and selected by service "upf".
    assert o["workload"] == "upf"
    assert o["service"] == "upf"


def test_owners_missing_pod_is_safe():
    g = build_demo_graph()
    o = g.owners("does-not-exist")
    assert o == {"workload": None, "workload_kind": None, "service": None}


def test_report_has_upstream_and_blast_radius_fields():
    from rca_agent.config import Settings
    from rca_agent.models.alert import Alert
    from rca_agent.reasoning.flow import ReasoningFlow

    settings = Settings(cluster_enabled=False, reasoning_mode="extractive")
    flow = ReasoningFlow(settings, graph=build_demo_graph())
    alert = Alert(labels={"alertname": "PodOOM", "namespace": "open5gs", "pod": "upf-1"},
                  annotations={"description": "OOMKilled"})
    report = flow.run(alert)
    # Fields exist and are lists (demo graph has no calls edges, so they may be
    # empty — the point is the report carries them for the UI to render).
    assert isinstance(report.upstream_unhealthy, list)
    assert isinstance(report.blast_radius, list)
