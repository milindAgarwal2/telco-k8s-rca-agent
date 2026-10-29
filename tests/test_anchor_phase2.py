"""Phase 2 tests: service-anchored graph walk gives SYMMETRIC upstream &
downstream (the previously-always-empty-downstream fix)."""
from __future__ import annotations

from rca_agent.config import Settings
from rca_agent.graph.dependency_graph import (
    DependencyGraph,
    EdgeKind,
    Health,
    NodeKind,
)
from rca_agent.models.alert import Alert
from rca_agent.reasoning.flow import ReasoningFlow


def _graph_with_calls():
    """A -> B -> C dependency chain at the SERVICE level, each service backed by
    one pod. caller-pod calls service/B; B's pod calls service/C.

    service/A --selects--> a-pod --calls--> service/B --selects--> b-pod
      --calls--> service/C --selects--> c-pod
    """
    g = DependencyGraph()
    for svc, pod, healthy in [("A", "a-pod", True), ("B", "b-pod", False),
                              ("C", "c-pod", False)]:
        g.upsert_node(f"service/{svc}", NodeKind.service, display=svc)
        g.upsert_node(pod, NodeKind.pod, healthy=healthy,
                      health=(Health.healthy if healthy else Health.down).value,
                      health_reason="probe failed" if not healthy else "ready")
        g.upsert_edge(f"service/{svc}", pod, EdgeKind.selects)
    g.upsert_edge("a-pod", "service/B", EdgeKind.calls, evidence="env:B_ADDR")
    g.upsert_edge("b-pod", "service/C", EdgeKind.calls, evidence="env:C_ADDR")
    for svc in ("A", "B", "C"):
        g.roll_up_service_health(f"service/{svc}")
    return g


def test_downstream_blast_radius_is_not_empty_for_pod_incident():
    """Incident fires on b-pod. Anchored on service/B, downstream must include
    service/A (A calls B) — the fix for the previously-empty downstream."""
    g = _graph_with_calls()
    flow = ReasoningFlow(Settings(cluster_enabled=False), graph=g)
    alert = Alert(labels={"alertname": "PodUnhealthy", "namespace": "ns",
                          "pod": "b-pod", "severity": "critical"},
                  annotations={"description": "probe failed"})
    report = flow.run(alert)

    assert report.anchor_kind == "service"
    assert report.affected_anchor == "service/B"
    # Downstream (blast radius): who depends on B. a-pod calls service/B, so
    # a-pod is in the blast radius — NOT empty (the fix). Previously, walking
    # only from b-pod, downstream was always empty.
    assert "a-pod" in report.blast_radius
    assert report.blast_radius, "downstream blast radius must not be empty"
    # Upstream (possible causes): what B depends on & is unhealthy -> service/C
    # (b-pod calls service/C, which is down).
    assert "service/C" in report.upstream_unhealthy
