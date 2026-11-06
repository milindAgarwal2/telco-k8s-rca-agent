"""Property-based test P9 for the potential-alarms feature.

Hypothesis property P9: attaching potential alarms never changes hypothesis
ranking. For any incident input, running the extractive pipeline with the
Potential Alarms feature ON produces a hypotheses list identical -- in count,
identity (cause), confidence value, and relative ordering -- to the list
produced with the feature OFF.

The feature wiring under test lives in ``reasoning/steps.build_potential_alarms``
(called from ``reasoning/extractive.ExtractivePipeline.run`` after
``hypothesize_and_rank``) and is gated by ``Settings.pod_alarm_map_path``: unset
=> ``load_potential_alarms_index`` returns ``None`` => feature OFF; set to the
committed workbook fixture => feature ON. ``build_potential_alarms`` only sets
``state.potential_alarms`` and appends one ``Evidence(category="alarms")`` -- it
must never create, remove, or reweight a ``Hypothesis`` (R5 AC2/AC3), so the two
runs' hypotheses must match exactly.

The cluster is a fixed offline fake (``tests.fake_kube``) so hypotheses have
real gathered evidence to rank; only the ALERT is generated, which drives which
pod the feature resolves (a mapped fixture pod, a hash-rolled stem variant of
one, or a wholly unmapped/absent pod) and thus whether the feature attaches
anything at all. The ranking invariant must hold across all three cases.

Kept in its own file (``_p9``) so it does not collide with the other
feature-level property tests (P10 serialization lives in
``test_incident_serialization_p10.py``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rca_agent.config import Settings
from rca_agent.graph.builder import GraphBuilder
from rca_agent.models.alert import Alert
from rca_agent.models.incident import Hypothesis
from rca_agent.reasoning.extractive import ExtractivePipeline
from tests import fake_kube as fk

FIXTURE = str(Path(__file__).parent / "fixtures" / "pod_alarm_mapping_sample.xlsx")
NAMESPACE = "plantx2avzwcspgc-y-oc-consp-301"

# Pods mapped in the committed pod-alarm fixture (exact names). Using these as
# alert targets exercises the feature-ON attach path.
MAPPED_FORWARDER = "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm"
MAPPED_ROUTING = "eric-pc-routing-engine-5d4d546b64-bh9px"
MAPPED_CERTM = "eric-sec-certm-7d8f9dfc56-f7rpv"

# A hash-rolled variant of a mapped pod: NOT an exact key, but shares the
# hash-stripped stem, so the index resolves it via the stem fallback (R1 AC4).
STEM_VARIANT_FORWARDER = "eric-pc-vpn-gateway-forwarder-85c5f46fc5-aaaaa"

# Pods never present in the fixture: the feature resolves them as UNKNOWN and
# attaches nothing, so feature-ON == feature-OFF trivially for these.
UNMAPPED_POD = "totally-unknown-pod-xyz-123"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store() -> dict:
    """A fixed offline cluster giving every candidate target real, rankable
    evidence (an OOMKilled fault + a recent correlated ConfigMap edit), so the
    hypotheses list is non-trivial and the ranking invariant is meaningful.

    Every pod that an alert may target is present here so ``graph_walk`` and
    ``gather_evidence`` resolve it; the alarm feature's attach decision (mapped
    vs UNKNOWN) is driven purely by the pod-alarm fixture, independent of this
    cluster.
    """
    recent = _now() - timedelta(minutes=3)
    pods = []
    replicasets = []
    deployments = []
    # Each target pod: an OOMKilled fault owned by its own ReplicaSet so the
    # anchor resolves and a fault hypothesis is produced.
    for pod_name, rs_name, deploy_name in (
        (MAPPED_FORWARDER, "eric-pc-vpn-gateway-forwarder-85c5f46fc5",
         "eric-pc-vpn-gateway-forwarder"),
        (STEM_VARIANT_FORWARDER, "eric-pc-vpn-gateway-forwarder-85c5f46fc5",
         "eric-pc-vpn-gateway-forwarder"),
        (MAPPED_ROUTING, "eric-pc-routing-engine-5d4d546b64",
         "eric-pc-routing-engine"),
        (MAPPED_CERTM, "eric-sec-certm-7d8f9dfc56", "eric-sec-certm"),
        (UNMAPPED_POD, "totally-unknown-pod-xyz-123-rs", "totally-unknown-pod-xyz"),
    ):
        pods.append(fk.pod(pod_name, node_name="worker-1", healthy=False,
                           oomkilled=True, restart_count=3,
                           owner_refs=[fk.owner(rs_name)]))
        replicasets.append(fk.replicaset(rs_name, deploy_name, replicas=1))
        deployments.append(fk.deployment(deploy_name, replicas=1))

    events = [
        fk.event(p.metadata.name, "OOMKilled",
                 f"Container app in {p.metadata.name} was OOMKilled",
                 last_timestamp=recent)
        for p in pods
    ]
    logs = {
        p.metadata.name: {"previous": 'level=error msg="out of memory"',
                          "current": "level=info msg=up"}
        for p in pods
    }
    return {
        "nodes": [fk.node("worker-1")],
        "pods": pods,
        "events": events,
        "logs": logs,
        "configmaps": [fk.configmap("app-config", modified=recent)],
        "secrets": [],
        "pvcs": [],
        "replicasets": replicasets,
        "deployments": deployments,
        "services": [],
    }


# Built once: the cluster is fixed across examples; only the alert varies.
_STORE = _store()


def _hyp_signature(hyps: list[Hypothesis]) -> list[tuple[str, float]]:
    """Order-preserving projection to the facets P9 pins: identity (cause) and
    confidence, in the produced relative order. Equal signatures => same count,
    same identities, same confidences, same ordering."""
    return [(h.cause, h.confidence) for h in hyps]


def _run(pod_alarm_map_path: str | None, alert: Alert) -> list[Hypothesis]:
    """Run the extractive pipeline over the fixed fake cluster with the alarm
    feature OFF (path None) or ON (fixture path), returning the ranked
    hypotheses. A fresh builder/pipeline per run avoids any cross-run state."""
    cfg = Settings(cluster_enabled=True, namespace=NAMESPACE,
                   pod_alarm_map_path=pod_alarm_map_path)
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(_STORE))
    pipeline = ExtractivePipeline(cfg, builder=builder)
    return pipeline.run(alert).hypotheses


# Alert targets spanning the three feature outcomes: an exact mapped hit, a
# stem-fallback hit, and an UNKNOWN miss -- plus a couple more mapped pods.
_TARGET = st.sampled_from([
    MAPPED_FORWARDER,
    MAPPED_ROUTING,
    MAPPED_CERTM,
    STEM_VARIANT_FORWARDER,
    UNMAPPED_POD,
])
_ALERTNAME = st.sampled_from([
    "KubePodNotReady", "HighErrorRate", "PodUnhealthy", "OOMKilled",
])
_SEVERITY = st.sampled_from(["critical", "warning"])


# Feature: potential-alarms, Property 9: Attaching potential alarms never
# changes hypothesis ranking
#
# deadline=None: each example runs the full extractive pipeline TWICE (feature
# off then on), so a per-example wall-clock deadline measures pipeline cost, not
# a correctness regression -- the cold first call (module/graph import) alone
# exceeds Hypothesis's 200ms default. P9 is about ranking equality, not timing.
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(target=_TARGET, alertname=_ALERTNAME, severity=_SEVERITY)
def test_p9_potential_alarms_never_change_ranking(
    target: str,
    alertname: str,
    severity: str,
) -> None:
    """For any incident input, the hypotheses produced with the feature ON are
    identical to those produced with the feature OFF, in count, identity,
    confidence value, and relative ordering.

    Validates: Requirements 5.2, 5.3
    """
    alert = Alert(labels={
        "alertname": alertname,
        "pod": target,
        "namespace": NAMESPACE,
        "severity": severity,
    })

    hyps_off = _run(None, alert)
    hyps_on = _run(FIXTURE, alert)

    # Identical in count, identity (cause), confidence, and relative ordering.
    assert _hyp_signature(hyps_on) == _hyp_signature(hyps_off)
