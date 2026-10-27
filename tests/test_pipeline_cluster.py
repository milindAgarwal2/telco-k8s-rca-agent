"""End-to-end: the extractive pipeline produces a real root-cause report from
live cluster evidence (via KubeQueryTools over a fake client), not stub data.

Two regression guards:
  * "KubeQueryTools wired into reasoning" — an OOMKilled pod plus a correlated
    recent ConfigMap edit must surface as the top hypothesis with an evidence
    chain drawn from the cluster.
  * "probe-failure hypotheses" (0.3.2) — a pod that is Running but failing its
    readiness/liveness probe (no OOMKilled/CrashLoopBackOff) must itself rank
    as the top root cause instead of being invisible to the fault detector.
  * "calls edges" (0.3.5) — a pod whose env var literally references another
    Service, where that Service is unhealthy, must get an upstream-dependency
    hypothesis naming it, cited with the exact env var/ConfigMap key that
    produced the edge — not just a generic "pod failing health probe" guess
    with no named cause (the eric-pc-sm-* outage's real gap).
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


def _upstream_dependency_store():
    """``eric-pc-sm-diameter-0`` (the alert target) references the
    ``eric-pc-sm-target-database`` Service via a literal env var; that
    service's own pod is CrashLoopBackOff. This is the shape of the real
    eric-pc-sm-* outage, minus the part this agent still can't do (there was
    no such env var on the real cluster, or this would have named the cause
    then too)."""
    caller = fk.pod(
        "eric-pc-sm-diameter-0", node_name="worker-1", healthy=True,
        owner_refs=[fk.owner("eric-pc-sm-diameter-rs")],
        containers=[fk.container(env=[
            fk.env_var("TARGET_DB_HOST", value="eric-pc-sm-target-database"),
        ])],
    )
    dependency = fk.pod(
        "eric-pc-sm-target-database-0", node_name="worker-1", healthy=False,
        waiting_reason="CrashLoopBackOff",
        owner_refs=[fk.owner("eric-pc-sm-target-database-rs")],
        labels={"app.kubernetes.io/name": "eric-pc-sm-target-database"},
    )
    return {
        "nodes": [fk.node("worker-1")],
        "pods": [caller, dependency],
        "events": [],
        "logs": {},
        "configmaps": [], "secrets": [], "pvcs": [],
        "replicasets": [
            fk.replicaset("eric-pc-sm-diameter-rs", "eric-pc-sm-diameter", replicas=1),
            fk.replicaset("eric-pc-sm-target-database-rs", "eric-pc-sm-target-database",
                          replicas=1),
        ],
        "deployments": [
            fk.deployment("eric-pc-sm-diameter", replicas=1),
            fk.deployment("eric-pc-sm-target-database", replicas=1),
        ],
        "services": [fk.service("eric-pc-sm-target-database",
                                selector={"app.kubernetes.io/name":
                                         "eric-pc-sm-target-database"})],
    }


def test_pipeline_names_the_real_upstream_dependency_via_calls_edge():
    """Regression for the calls-edges feature (0.3.5): when a pod's env var
    literally references another Service, and that service is unhealthy,
    the report must name it as an upstream cause with a cited env-var
    evidence — not just flag a correlation pattern or a generic guess."""
    cfg = Settings(cluster_enabled=True, namespace="open5gs")
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(_upstream_dependency_store()))
    pipeline = ExtractivePipeline(cfg, builder=builder)

    alert = Alert(labels={"alertname": "DiameterErrors", "pod": "eric-pc-sm-diameter-0",
                          "namespace": "open5gs", "severity": "critical"})
    report = pipeline.run(alert)

    upstream_hyps = [h for h in report.hypotheses
                     if "service/eric-pc-sm-target-database" in h.cause]
    assert upstream_hyps, (
        f"expected an upstream-dependency hypothesis naming the DB service; "
        f"got causes: {[h.cause for h in report.hypotheses]}"
    )

    graph_evidence = [e for e in report.evidence if e.category == "graph"
                      and e.resource == "service/eric-pc-sm-target-database"]
    assert graph_evidence, "expected graph evidence citing the unhealthy upstream service"
    assert "env:TARGET_DB_HOST" in graph_evidence[0].citations[0].detail
