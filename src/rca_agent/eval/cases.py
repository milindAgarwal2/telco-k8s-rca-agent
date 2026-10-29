"""The fault library: labeled synthetic cases with a KNOWN root cause.

Each :class:`FaultCase` builds a fake-kube store + the triggering alert, and
declares a ``ground_truth`` matcher that recognises the correct root cause in a
ranked :class:`~rca_agent.models.incident.Hypothesis`. The runner feeds the
store through the real pipeline; the scorer checks the ground truth against the
top-2 hypotheses.

Cause-string formats produced by ``reasoning/steps.py`` (what the matchers key
on):
  * fault event:     "<pod> OOMKilled" / "<pod> CrashLoopBackOff" / "<pod> ImagePullBackOff"
  * probe failure:   "<pod> failing health probe (...)"
  * recent change:   "recent <type> to <object>"
  * unhealthy upstream: "<svc> unhealthy (cascades to <pod>)"
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from rca_agent.eval import fake_cluster as fc
from rca_agent.models.alert import Alert
from rca_agent.models.incident import Hypothesis


def _now() -> datetime:
    return datetime.now(timezone.utc)


# A ground-truth matcher: given a Hypothesis, is THIS the correct root cause?
Matcher = Callable[[Hypothesis], bool]


def cause_contains(*needles: str) -> Matcher:
    """Match when the hypothesis cause contains ALL needles (case-insensitive)."""
    lowered = [n.lower() for n in needles]
    return lambda h: all(n in (h.cause or "").lower() for n in lowered)


@dataclass
class FaultCase:
    """One labeled fault: a fixture + the alert + the known-correct cause."""

    id: str
    fault_type: str
    description: str
    # Builds the fake-kube store (the injected cluster state).
    build_store: Callable[[], dict]
    # The alert that triggers reasoning (what detection would hand the pipeline).
    alert: Alert
    # Recognises the correct root cause among ranked hypotheses.
    ground_truth: Matcher
    # Human-readable description of the expected cause, for the results table.
    expected: str
    namespace: str = "open5gs"


# ---------------------------------------------------------------------------
# Fixture builders — each injects ONE known fault (plus healthy context).
# ---------------------------------------------------------------------------

def _recent(minutes: int = 3) -> datetime:
    return _now() - timedelta(minutes=minutes)


def _oomkilled_store() -> dict:
    s = fc.empty_store()
    s["nodes"] = [fc.node("worker-1")]
    s["pods"] = [fc.pod("upf-0", node_name="worker-1", healthy=False,
                        oomkilled=True, restart_count=3,
                        labels={"app": "upf"})]
    s["events"] = [fc.event("upf-0", "OOMKilled",
                            "Container app was OOMKilled (memory limit exceeded)",
                            last_timestamp=_recent())]
    s["services"] = [fc.service("upf", {"app": "upf"})]
    return s


def _crashloop_store() -> dict:
    s = fc.empty_store()
    s["nodes"] = [fc.node("worker-1")]
    s["pods"] = [fc.pod("smf-0", node_name="worker-1", healthy=False,
                        waiting_reason="CrashLoopBackOff", restart_count=7,
                        labels={"app": "smf"})]
    s["events"] = [fc.event("smf-0", "CrashLoopBackOff",
                            "Back-off restarting failed container",
                            last_timestamp=_recent())]
    s["services"] = [fc.service("smf", {"app": "smf"})]
    return s


def _imagepull_store() -> dict:
    s = fc.empty_store()
    s["nodes"] = [fc.node("worker-1")]
    s["pods"] = [fc.pod("amf-0", node_name="worker-1", healthy=False,
                        phase="Pending", waiting_reason="ImagePullBackOff",
                        labels={"app": "amf"})]
    s["events"] = [fc.event("amf-0", "ImagePullBackOff",
                            "Back-off pulling image amf:v9.9.9-does-not-exist",
                            last_timestamp=_recent())]
    s["services"] = [fc.service("amf", {"app": "amf"})]
    return s


def _probe_failure_store() -> dict:
    s = fc.empty_store()
    s["nodes"] = [fc.node("worker-1")]
    # Running but failing readiness probe (1/2 ready, HTTP 500) — the classic
    # eric-pc-sm-* signature. No terminated/OOM reason.
    s["pods"] = [fc.pod("diameter-0", node_name="worker-1", healthy=False,
                        phase="Running", labels={"app": "diameter"})]
    s["events"] = [fc.event("diameter-0", "Unhealthy",
                            "Readiness probe failed: HTTP probe failed with "
                            "statuscode: 500", last_timestamp=_recent())]
    s["services"] = [fc.service("diameter", {"app": "diameter"})]
    return s


def _bad_configmap_store() -> dict:
    """A ConfigMap the pod MOUNTS was edited just before it went unhealthy —
    the headline 'bad config value' case (mount-scoped change correlation)."""
    s = fc.empty_store()
    s["nodes"] = [fc.node("worker-1")]
    s["configmaps"] = [fc.configmap("upf-config", modified=_recent(2),
                                    data={"upf.yaml": "pfcp_addr: 10.0.0.9"})]
    s["pods"] = [fc.pod("upf-0", node_name="worker-1", healthy=False,
                        phase="Running",
                        volumes=[fc.cm_volume("upf-config")],
                        labels={"app": "upf"})]
    s["events"] = [fc.event("upf-0", "Unhealthy",
                            "Readiness probe failed: config rejected",
                            last_timestamp=_recent())]
    s["services"] = [fc.service("upf", {"app": "upf"})]
    return s


def _unhealthy_upstream_store() -> dict:
    """SMF depends on (calls) UPF via an env var; UPF is down -> cascade.

    The calls edge is built from the literal env var value naming the UPF
    service, exactly as graph/builder.py::_add_call_edges does.
    """
    s = fc.empty_store()
    s["nodes"] = [fc.node("worker-1")]
    # UPF: down (OOMKilled) — the real upstream cause. The service name must be
    # >= 4 chars for the calls-edge heuristic (_MIN_MATCH_NAME_LEN), so 'upf-east'.
    upf = fc.pod("upf-east-0", node_name="worker-1", healthy=False, oomkilled=True,
                 restart_count=2, labels={"app": "upf-east"})
    # SMF: running but references the UPF service by name in an env var.
    smf = fc.pod("smf-0", node_name="worker-1", healthy=False, phase="Running",
                 labels={"app": "smf"},
                 containers=[fc.container(
                     "app", env=[fc.env_var("UPF_SERVICE_ADDR",
                                            value="http://upf-east:8805")])])
    s["pods"] = [upf, smf]
    s["events"] = [
        fc.event("upf-east-0", "OOMKilled", "Container app was OOMKilled",
                 last_timestamp=_recent()),
        fc.event("smf-0", "Unhealthy",
                 "Readiness probe failed: upstream UPF unreachable",
                 last_timestamp=_recent()),
    ]
    s["services"] = [fc.service("upf-east", {"app": "upf-east"}),
                     fc.service("smf", {"app": "smf"})]
    return s


def _node_not_ready_store() -> dict:
    """A worker node went NotReady; its pod is Pending/unschedulable."""
    s = fc.empty_store()
    s["nodes"] = [fc.node("worker-2", ready=False)]
    s["pods"] = [fc.pod("pcf-0", node_name="worker-2", healthy=False,
                        phase="Pending", waiting_reason="NodeNotReady",
                        labels={"app": "pcf"})]
    s["events"] = [fc.event("pcf-0", "NodeNotReady",
                            "Node worker-2 status is now: NodeNotReady",
                            last_timestamp=_recent())]
    s["services"] = [fc.service("pcf", {"app": "pcf"})]
    return s


def _multi_fault_store() -> dict:
    """Two SIMULTANEOUS, independent faults: upf OOMKilled and amf ImagePull.
    Tests whether the agent keeps them as separate hypotheses (both should be
    present); the case's ground truth is the upf OOMKilled one (the alert target).
    """
    s = fc.empty_store()
    s["nodes"] = [fc.node("worker-1")]
    s["pods"] = [
        fc.pod("upf-0", node_name="worker-1", healthy=False, oomkilled=True,
               restart_count=4, labels={"app": "upf"}),
        fc.pod("amf-0", node_name="worker-1", healthy=False, phase="Pending",
               waiting_reason="ImagePullBackOff", labels={"app": "amf"}),
    ]
    s["events"] = [
        fc.event("upf-0", "OOMKilled", "Container app was OOMKilled",
                 last_timestamp=_recent()),
        fc.event("amf-0", "ImagePullBackOff", "Back-off pulling image amf:bad",
                 last_timestamp=_recent()),
    ]
    s["services"] = [fc.service("upf", {"app": "upf"}),
                     fc.service("amf", {"app": "amf"})]
    return s


def _alert(name: str, target: str, ns: str = "open5gs",
           severity: str = "critical") -> Alert:
    # Alert.name/target/namespace are READ-ONLY properties derived from labels,
    # so the triggering identity must be expressed through labels.
    return Alert(status="firing", starts_at=_now(),
                 labels={"alertname": name, "pod": target,
                         "namespace": ns, "severity": severity},
                 annotations={})


# ---------------------------------------------------------------------------
# The library.
# ---------------------------------------------------------------------------

FAULT_LIBRARY: list[FaultCase] = [
    FaultCase(
        id="oomkilled",
        fault_type="OOMKilled",
        description="UPF pod OOMKilled (memory limit exceeded).",
        build_store=_oomkilled_store,
        alert=_alert("PodOOMKilled", "upf-0"),
        ground_truth=cause_contains("upf-0", "oomkilled"),
        expected="upf-0 OOMKilled",
    ),
    FaultCase(
        id="crashloop",
        fault_type="CrashLoopBackOff",
        description="SMF pod stuck in CrashLoopBackOff.",
        build_store=_crashloop_store,
        alert=_alert("PodCrashLooping", "smf-0"),
        ground_truth=cause_contains("smf-0", "crashloop"),
        expected="smf-0 CrashLoopBackOff",
    ),
    FaultCase(
        id="imagepull",
        fault_type="ImagePullBackOff",
        description="AMF pod cannot pull its image (bad tag).",
        build_store=_imagepull_store,
        alert=_alert("PodImagePullBackOff", "amf-0"),
        ground_truth=cause_contains("amf-0", "imagepull"),
        expected="amf-0 ImagePullBackOff",
    ),
    FaultCase(
        id="probe_failure",
        fault_type="ProbeFailure",
        description="Running pod failing its readiness probe (HTTP 500).",
        build_store=_probe_failure_store,
        alert=_alert("PodNotReady", "diameter-0"),
        ground_truth=cause_contains("diameter-0", "probe"),
        expected="diameter-0 failing health probe",
    ),
    FaultCase(
        id="bad_configmap",
        fault_type="BadConfigChange",
        description="A mounted ConfigMap was edited just before the pod failed.",
        build_store=_bad_configmap_store,
        alert=_alert("PodNotReady", "upf-0"),
        ground_truth=cause_contains("upf-config"),
        expected="recent configmap_update to upf-config",
    ),
    FaultCase(
        id="unhealthy_upstream",
        fault_type="UpstreamCascade",
        description="SMF unhealthy because the UPF it calls is down (cascade).",
        build_store=_unhealthy_upstream_store,
        alert=_alert("PodNotReady", "smf-0"),
        # Correct cause names the upstream UPF service as the cascade source.
        ground_truth=cause_contains("upf", "cascade"),
        expected="service/upf unhealthy (cascades to smf-0)",
    ),
    FaultCase(
        id="node_not_ready",
        fault_type="NodeNotReady",
        description="Pod unschedulable because its node went NotReady.",
        build_store=_node_not_ready_store,
        alert=_alert("PodNotReady", "pcf-0"),
        # Offline, the strongest grounded signal is the pod's own not-ready/
        # NodeNotReady status; accept either the node-named or probe framing.
        ground_truth=lambda h: ("pcf-0" in (h.cause or "").lower()) and (
            "probe" in (h.cause or "").lower()
            or "nodenotready" in (h.cause or "").lower()
            or "not ready" in (h.cause or "").lower()),
        expected="pcf-0 not ready (node worker-2 NotReady)",
    ),
    FaultCase(
        id="multi_fault_separation",
        fault_type="MultiFault",
        description="Two simultaneous independent faults; alert targets upf-0.",
        build_store=_multi_fault_store,
        alert=_alert("PodOOMKilled", "upf-0"),
        ground_truth=cause_contains("upf-0", "oomkilled"),
        expected="upf-0 OOMKilled (amf-0 ImagePull is a separate incident)",
    ),
]
