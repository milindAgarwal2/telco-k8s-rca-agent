"""Phase 3 test: with anchor-dedup handling same-anchor siblings, correlation
now links DIFFERENT anchors sharing a failure signature (cross-service pattern)."""
from __future__ import annotations

from rca_agent.config import Settings
from rca_agent.detection.event_watcher import EventWatcher
from rca_agent.graph.builder import GraphBuilder
from rca_agent.models.incident import Hypothesis, IncidentReport
from tests import fake_kube as fk


def _empty_watcher():
    cfg = Settings(cluster_enabled=True, namespace="open5gs")
    store = {"nodes": [], "pods": [], "events": [], "logs": {}, "configmaps": [],
             "secrets": [], "pvcs": [], "replicasets": [], "deployments": [],
             "services": []}
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(store))
    builder.rebuild()
    flow = None
    return EventWatcher(cfg, builder, flow_factory=lambda: flow)


def _svc_incident(anchor: str) -> IncidentReport:
    cause = f"{anchor} failing health probe (HTTP probe failed with statuscode: 500)"
    return IncidentReport(
        symptom=f"PodPersistentlyUnhealthy on {anchor}",
        affected_resource=anchor,
        affected_anchor=anchor,
        anchor_kind="service",
        hypotheses=[Hypothesis(cause=cause, confidence=0.5,
                               evidence_chain=[f"symptom: ... on {anchor}"])],
    )


def test_different_anchors_same_signature_are_correlated():
    w = _empty_watcher()
    a = _svc_incident("service/eric-pc-sm-diameter")
    b = _svc_incident("service/eric-pc-sm-sgw-session")

    w.record_external_incident(a)
    w.record_external_incident(b)

    # Different anchors, identical probe-failure signature -> linked.
    assert a.incident_id in b.related_incidents
    assert b.incident_id in a.related_incidents
    assert any(s.startswith("Correlated:") for s in a.suggested_next_steps)


def test_same_anchor_is_not_double_counted_by_correlation():
    """Two incidents on the SAME anchor must NOT be correlation-linked (that's
    the dedup path's job); correlation only links across anchors."""
    w = _empty_watcher()
    a = _svc_incident("service/eric-pc-sm-diameter")
    b = _svc_incident("service/eric-pc-sm-diameter")  # same anchor

    w.record_external_incident(a)
    w.record_external_incident(b)

    assert a.related_incidents == []
    assert b.related_incidents == []
