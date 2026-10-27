"""End-to-end: the extractive pipeline produces a real root-cause report from
live cluster evidence (via KubeQueryTools over a fake client), not stub data.

Two regression guards:
  * "KubeQueryTools wired into reasoning" — an OOMKilled pod plus a correlated
    recent ConfigMap edit must surface as the top hypothesis with an evidence
    chain drawn from the cluster.
  * "probe-failure hypotheses" (0.3.2) — a pod that is Running but failing its
    readiness/liveness probe (no OOMKilled/CrashLoopBackOff) must itself rank
    as the top root cause instead of being invisible to the fault detector.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rca_agent.config import Settings
from rca_agent.graph.builder import GraphBuilder
from rca_agent.models.alert import Alert
from rca_agent.reasoning.extractive import ExtractivePipeline
from tests import fake_kube as fk


def _now():
    return datetime.now(timezone.utc)


def _store():
    recent = _now() - timedelta(minutes=3)
    return {
        "nodes": [fk.node("worker-1")],
        "pods": [
            fk.pod("upf-7c9-bbbb", node_name="worker-1", healthy=False,
                   oomkilled=True, restart_count=4,
                   owner_refs=[fk.owner("upf-7c9")]),
        ],
        "events": [
            fk.event("upf-7c9-bbbb", "OOMKilled",
                     "Container upf was OOMKilled", last_timestamp=recent),
        ],
        "logs": {
            "upf-7c9-bbbb": {
                "previous": 'level=error msg="out of memory"',
                "current": "level=info msg=up",
            },
        },
        "configmaps": [fk.configmap("upf-config", modified=recent)],
        "secrets": [],
        "pvcs": [],
        "replicasets": [fk.replicaset("upf-7c9", "upf", replicas=1)],
        "deployments": [fk.deployment("upf", replicas=1)],
        "services": [],
    }


def test_pipeline_produces_real_report_from_cluster_evidence():
    cfg = Settings(cluster_enabled=True, namespace="open5gs")
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(_store()))
    pipeline = ExtractivePipeline(cfg, builder=builder)

    # The query tools must be the REAL implementation, not the stub.
    from rca_agent.tools.query_tools import KubeQueryTools
    assert isinstance(pipeline.tools, KubeQueryTools)

    alert = Alert(labels={"alertname": "HighErrorRate", "pod": "upf-7c9-bbbb",
                          "namespace": "open5gs", "severity": "critical"})
    report = pipeline.run(alert)

    # A hypothesis exists and the top one is the OOMKilled fault.
    assert report.hypotheses, "expected at least one ranked hypothesis"
    top = report.hypotheses[0]
    assert "OOMKilled" in top.cause

    # Evidence is drawn from the cluster: an OOM event, a crash log line, and the
    # correlated recent configmap change — none of which come from the stub.
    categories = {e.category for e in report.evidence}
    assert "event" in categories
    assert "log" in categories
    assert "change" in categories
    summaries = " ".join(e.summary for e in report.evidence)
    assert "out of memory" in summaries          # from real pod logs
    assert "upf-config" in summaries             # from real recent_changes


def _probe_store():
    """A pod that is Running but failing its readiness probe — no OOM/crash."""
    return {
        "nodes": [fk.node("worker-1")],
        "pods": [
            fk.pod("eric-pc-sm-diameter-7bdcb67999-7tcd2", node_name="worker-1",
                   healthy=False, restart_count=0,
                   owner_refs=[fk.owner("eric-pc-sm-diameter-7bdcb67999")]),
        ],
        "events": [
            fk.event("eric-pc-sm-diameter-7bdcb67999-7tcd2", "Unhealthy",
                     "Readiness probe failed: HTTP probe failed with "
                     "statuscode: 500", last_timestamp=_now() - timedelta(minutes=1)),
        ],
        "logs": {},
        "configmaps": [],
        "secrets": [],
        "pvcs": [],
        "replicasets": [fk.replicaset("eric-pc-sm-diameter-7bdcb67999",
                                      "eric-pc-sm-diameter", replicas=1)],
        "deployments": [fk.deployment("eric-pc-sm-diameter", replicas=1)],
        "services": [],
    }


def test_probe_failure_ranks_as_top_hypothesis_without_oom_or_crash():
    """Regression: a pod failing its readiness probe (Running, no OOMKilled/
    CrashLoopBackOff) must itself surface as the top root-cause hypothesis —
    not get buried beneath, or overridden by, unrelated signals. This is the
    `eric-pc-sm-diameter` case from the real Cobra cluster: the pod was up but
    returning 500s on its readiness probe.
    """
    cfg = Settings(cluster_enabled=True, namespace="plantx2avzwcspgc-y-oc-consp-301")
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(_probe_store()))
    pipeline = ExtractivePipeline(cfg, builder=builder)

    alert = Alert(labels={
        "alertname": "PodUnhealthy",
        "pod": "eric-pc-sm-diameter-7bdcb67999-7tcd2",
        "namespace": "plantx2avzwcspgc-y-oc-consp-301",
        "severity": "critical",
    })
    report = pipeline.run(alert)

    assert report.hypotheses, "expected at least one ranked hypothesis"
    top = report.hypotheses[0]
    assert "probe" in top.cause.lower()
    assert "500" in " ".join(top.evidence_chain)
    assert top.confidence > 0.0
    # No OOMKilled/CrashLoopBackOff signal was ever present for this pod.
    assert "OOMKilled" not in top.cause
    assert "CrashLoopBackOff" not in top.cause
