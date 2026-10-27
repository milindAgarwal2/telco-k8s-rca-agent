"""Unit tests for the graph layer and the extractive reasoning pipeline."""
from __future__ import annotations

from rca_agent.graph.dependency_graph import EdgeKind, Health, NodeKind, build_demo_graph
from rca_agent.models.alert import Alert
from rca_agent.reasoning.extractive import ExtractivePipeline


def test_demo_graph_is_pod_centric():
    g = build_demo_graph()
    # The demo models ONE app (upf) as a workload with pods, matching the real
    # cluster builder — not NF-to-NF topology.
    assert g.node("upf")["kind"] == NodeKind.deployment.value
    for pod in ("upf-0", "upf-1", "upf-2"):
        assert g.node(pod)["kind"] == NodeKind.pod.value
    # No NF 'calls' edges exist in single-app scope.
    assert not any(k == EdgeKind.calls.value for _, _, k in g.graph.edges(keys=True))
    assert g.stats()["nodes"] > 0


def test_demo_graph_pod_edges_and_rollup():
    g = build_demo_graph()
    gg = g.graph
    assert gg.has_edge("upf-0", "worker-1", key=EdgeKind.runs_on.value)
    assert gg.has_edge("upf-0", "upf-7c9", key=EdgeKind.managed_by.value)
    assert gg.has_edge("upf-7c9", "upf", key=EdgeKind.managed_by.value)
    assert gg.has_edge("upf-0", "configmap/upf-config", key=EdgeKind.mounts.value)
    assert gg.has_edge("service/upf", "upf-0", key=EdgeKind.selects.value)
    # One pod OOMKilled -> workload degraded (2/3 ready).
    assert g.node("upf")["health"] == Health.degraded.value
    assert g.node("upf-1")["health_reason"] == "OOMKilled"


def test_timestamped_changes_recorded():
    g = build_demo_graph()
    before = len(g.changes)
    g.upsert_node("new-pod", NodeKind.pod, healthy=True)
    g.upsert_edge("new-pod", "upf-7c9", EdgeKind.managed_by)
    assert len(g.changes) == before + 2


def test_extractive_pipeline_ranks_root_cause():
    """UPF OOMKilled + ConfigMap change should outrank other candidates."""
    g = build_demo_graph()
    g.set_health("upf", healthy=False, reason="OOMKilled")

    alert = Alert(
        status="firing",
        labels={"alertname": "SMFHighErrorRate", "namespace": "open5gs",
                "pod": "upf-0", "severity": "critical"},
        annotations={"description": "SMF errors, PFCP down"},
    )
    report = ExtractivePipeline(graph=g).run(alert)

    assert report.hypotheses, "expected at least one hypothesis"
    top = report.top_hypothesis
    assert top is not None
    # The OOMKilled fault (linked to the ConfigMap change) should rank first.
    assert "OOMKilled" in " ".join(top.evidence_chain) or "upf" in top.cause.lower()
    assert top.confidence > 0.0
    assert report.suggested_next_steps, "runbook next-steps should be populated"
    assert report.reasoning_mode == "extractive"


def test_report_has_citations():
    alert = Alert(labels={"alertname": "UPFDown", "pod": "upf-0",
                          "namespace": "open5gs"})
    report = ExtractivePipeline().run(alert)
    assert report.evidence, "evidence should be gathered"
    # Every hypothesis chain starts with the symptom.
    for h in report.hypotheses:
        assert h.evidence_chain[0].startswith("symptom:")


def test_neighborhood_returns_subgraph():
    """Regression: neighborhood must not mutate its set while iterating."""
    g = build_demo_graph()
    nb = g.neighborhood("upf", radius=2)
    ids = {n["id"] for n in nb["nodes"]}
    assert "upf" in ids
    # radius 2 from the workload reaches its ReplicaSet (r=1) and pods (r=2).
    assert "upf-7c9" in ids
    assert any(p in ids for p in ("upf-0", "upf-1", "upf-2"))
    assert nb["edges"], "expected edges in the neighborhood"
