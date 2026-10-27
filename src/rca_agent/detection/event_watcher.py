"""Automatic fault detection from the live Kubernetes event stream.

Phase 1 "Event watcher" (see ``PLAN.md``): without this, the only way to get
an incident report is a human hand-crafting an Alertmanager webhook payload
for a pod they noticed was red. This polls the read-only kube client for
recent Warning events in the monitored namespace and feeds any recognized
fault event through the exact same reasoning entry point
(:class:`~rca_agent.reasoning.flow.ReasoningFlow`) that the webhook uses — so
a real failure is diagnosed automatically.

Design choices, deliberately conservative (read-only, rules-first, hard to
spam):

* **Scope** — only events whose ``involvedObject`` names a node that already
  exists in the *current* dependency graph are acted on. This piggybacks on
  whatever ``nf_selector``/namespace scoping the graph builder already does,
  with no separate event-side filtering needed, and skips event kinds
  (ConfigMap, Secret, ...) the reasoning pipeline doesn't target directly.
* **Trigger condition** — only the named fault reasons in
  ``KubeEvent.FAULT_REASONS`` (CrashLoopBackOff, OOMKilled, ImagePullBackOff,
  FailedScheduling, Unhealthy, FailedMount, NodeNotReady, Evicted, ...), NOT
  "any Warning event". A real cluster emits a lot of transient Warning noise
  (leader-election blips, scheduling retries that resolve themselves); acting
  on all of it would make the first automated feature untrustworthy.
* **Dedup** — a Kubernetes Event object keeps one stable UID while it recurs
  (``count``/``lastTimestamp`` update in place); we remember UIDs already
  turned into an incident so a long-lived CrashLoopBackOff isn't re-diagnosed
  every poll cycle. The seen-set is bounded so a long-running process can't
  grow it forever.

This module also doubles as the in-memory incident store (``self.incidents``)
for incidents created ANY way — auto-detected here, or posted manually via
``/webhook/alertmanager`` through :meth:`EventWatcher.record_external_incident`
— so both paths share one timeline and one correlation pool (see below).

**Incident correlation** (0.3.4): real on-cluster testing of the `eric-pc-sm-*`
outage showed the real gap isn't missing detection — it's that 12 pods failing
*identically* at once got reported as 12 fully independent, low-confidence
incidents with no link between them, because the real-cluster graph has no
NF-to-NF ``calls`` edges to name a shared upstream cause (see PLAN.md Known
Issues). Building real ``calls`` edges needs either a maintained static
service map (we have no authoritative source — guessing one would fabricate
exactly the kind of unsupported claim this project is built to avoid) or OTel
tracing (new infra, not something to stand up on someone else's cluster
unasked). So instead: :func:`_correlate` deterministically links incidents
that share an identical failure *signature* (same hypothesis text with the
affected resource name blanked out) on a *different* resource within
``incident_correlation_window_minutes``. It never claims what the shared cause
is and never touches a hypothesis's confidence — it only makes the honest,
citable pattern ("11 other resources failed the same way in the last 10
minutes") visible instead of silently fragmented across N unlinked incidents.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from rca_agent.config import Settings
from rca_agent.graph.builder import GraphBuilder
from rca_agent.models.alert import Alert, KubeEvent
from rca_agent.models.incident import IncidentReport
from rca_agent.reasoning.flow import ReasoningFlow

logger = logging.getLogger("rca_agent.detection")

_MAX_SEEN_UIDS = 2000   # bounded dedup memory
_MAX_STORED_INCIDENTS = 200  # bounded in-memory incident history

# Kind of the involved object -> the Alert label that resolves to it (mirrors
# Alert.target's lookup order in models/alert.py).
_KIND_TO_LABEL = {
    "Pod": "pod",
    "Deployment": "deployment",
    "StatefulSet": "statefulset",
    "Service": "service",
    "Job": "job",
    "Node": "instance",
}


class EventWatcher:
    """Polls K8s events; auto-feeds recognized faults into the reasoning flow.

    ``flow_factory`` is a zero-arg callable returning the CURRENT
    :class:`ReasoningFlow` — the webhook app rebuilds this object whenever the
    graph refreshes, so the watcher must look it up fresh each poll rather
    than caching a reference that could go stale.
    """

    def __init__(self, settings: Settings, builder: GraphBuilder,
                flow_factory: Callable[[], ReasoningFlow]) -> None:
        self.settings = settings
        self.builder = builder
        self._flow_factory = flow_factory
        self._seen_uids: OrderedDict[str, None] = OrderedDict()
        self.incidents: list[IncidentReport] = []

    def poll_once(self) -> list[IncidentReport]:
        """Run one polling cycle. Returns any newly-created incident reports."""
        kube = getattr(self.builder, "_kube", None)
        if kube is None:
            return []  # cluster client not built yet (first graph build still pending)

        ns = self.settings.namespace
        graph = self.builder.graph
        # Ignore events whose lastTimestamp predates "a few poll cycles ago" —
        # keeps a fresh watcher from flooding on ancient, no-longer-relevant
        # events, while still reacting to a genuinely ongoing fault (K8s
        # refreshes lastTimestamp on each recurrence of a live problem).
        cutoff = _now() - timedelta(
            seconds=max(60, self.settings.event_watch_interval_seconds * 4)
        )

        raw = _safe_list(lambda: kube.core.list_namespaced_event(ns), "events")
        new_reports: list[IncidentReport] = []
        for raw_event in raw:
            kev = _to_kube_event(raw_event, ns)
            # NB: FAULT_REASONS is a pydantic *field* (not a ClassVar) on
            # KubeEvent, so it's only readable off an instance, not the class.
            if kev.reason not in kev.FAULT_REASONS:
                continue
            if kev.last_seen and kev.last_seen < cutoff:
                continue
            if not kev.name or not graph.node(kev.name):
                continue  # out of scope: not a node the graph is monitoring

            uid = _event_uid(raw_event, kev)
            if uid in self._seen_uids:
                continue
            self._remember(uid)

            alert = _event_to_alert(kev, ns)
            try:
                report = self._flow_factory().run(alert)
            except Exception:
                logger.exception(
                    "event-watcher: reasoning failed for %s (%s)", kev.name, kev.reason
                )
                continue

            top = report.top_hypothesis
            logger.info(
                "event-watcher: auto-detected %s on %s -> incident %s (top=%s, confidence=%.2f)",
                kev.reason, kev.name, report.incident_id,
                top.cause if top else "none", top.confidence if top else 0.0,
            )
            self._store(report)
            new_reports.append(report)
        return new_reports

    def _remember(self, uid: str) -> None:
        self._seen_uids[uid] = None
        while len(self._seen_uids) > _MAX_SEEN_UIDS:
            self._seen_uids.popitem(last=False)

    def record_external_incident(self, report: IncidentReport) -> None:
        """Remember an incident diagnosed OUTSIDE the poll loop (i.e. a manual
        ``/webhook/alertmanager`` POST), so it shares the same ``/incidents``
        timeline and correlation pool as auto-detected ones. Safe to call for
        every report the webhook produces."""
        self._store(report)

    def _store(self, report: IncidentReport) -> None:
        self.incidents.append(report)
        if len(self.incidents) > _MAX_STORED_INCIDENTS:
            self.incidents.pop(0)
        self._correlate(report)

    def _correlate(self, report: IncidentReport) -> None:
        """Link ``report`` with any other stored incident that shares its
        exact failure signature on a DIFFERENT resource within the
        correlation window. Bidirectional and idempotent; never fabricates a
        cause, only flags the pattern (see module docstring)."""
        sig = _signature(report)
        if sig is None:
            return
        window_seconds = max(60, self.settings.incident_correlation_window_minutes * 60)
        linked_this_call = [report]
        for other in self.incidents:
            if other.incident_id == report.incident_id:
                continue
            if other.affected_resource == report.affected_resource:
                continue  # same resource -> not a "different resource" match
            if _signature(other) != sig:
                continue
            delta = abs((report.created_at - other.created_at).total_seconds())
            if delta > window_seconds:
                continue
            if other.incident_id not in report.related_incidents:
                report.related_incidents.append(other.incident_id)
            if report.incident_id not in other.related_incidents:
                other.related_incidents.append(report.incident_id)
            linked_this_call.append(other)
        if len(linked_this_call) > 1:
            by_id = {r.incident_id: r for r in self.incidents}
            for r in linked_this_call:
                _apply_correlation_note(r, by_id)

    def get_incident(self, incident_id: str) -> IncidentReport | None:
        return next((r for r in self.incidents if r.incident_id == incident_id), None)


_CORRELATION_NOTE_PREFIX = "Correlated: "


def _signature(report: IncidentReport) -> str | None:
    """A resource-independent fingerprint of the top hypothesis.

    Blanks out ``affected_resource`` inside the top hypothesis's ``cause``
    string, so "pod-A failing health probe (HTTP 500)" and "pod-B failing
    health probe (HTTP 500)" compare equal while "pod-A OOMKilled" does not.
    Returns None when there's nothing to compare (no hypothesis yet, or the
    resource name isn't actually inside the cause text).
    """
    top = report.top_hypothesis
    if top is None or not report.affected_resource:
        return None
    if report.affected_resource not in top.cause:
        return None
    return top.cause.replace(report.affected_resource, "<RESOURCE>")


def _apply_correlation_note(report: IncidentReport,
                            by_id: dict[str, IncidentReport]) -> None:
    """Keep exactly one up-to-date correlation note in ``suggested_next_steps``
    (replacing any stale one from an earlier, smaller group)."""
    report.suggested_next_steps = [
        s for s in report.suggested_next_steps if not s.startswith(_CORRELATION_NOTE_PREFIX)
    ]
    if not report.related_incidents:
        return
    related_resources = sorted({
        by_id[rid].affected_resource
        for rid in report.related_incidents
        if rid in by_id and by_id[rid].affected_resource
    })
    note = (
        f"{_CORRELATION_NOTE_PREFIX}{len(report.related_incidents)} other resource(s) failed "
        f"identically within the correlation window: {', '.join(related_resources)}. "
        "This pattern suggests a shared root cause, but the graph has no direct "
        "NF-to-NF dependency edge yet to confirm or name it — treat this as a "
        "signal to investigate shared dependencies by hand, not a verified cause."
    )
    report.suggested_next_steps.append(note)


# ---------------------------------------------------------------------------
# Helpers (tolerant of real kubernetes-client objects and the fake test client).
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_list(call, label: str) -> list:
    """Tolerate a 403/connection error on the event list — never crash the loop."""
    try:
        result = call()
        return getattr(result, "items", None) or []
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "status", None)
        reason = getattr(exc, "reason", None) or type(exc).__name__
        logger.warning("event-watcher: skipping %s: cannot list (%s %s)",
                       label, status, reason)
        return []


def _event_uid(raw_event, kev: KubeEvent) -> str:
    """A stable identity for dedup. Prefers the real K8s Event UID; falls back
    to a composite key for test doubles that don't carry one."""
    uid = getattr(getattr(raw_event, "metadata", None), "uid", None)
    if uid:
        return str(uid)
    return f"{kev.name}:{kev.reason}:{kev.first_seen}"


def _to_kube_event(raw_event, namespace: str) -> KubeEvent:
    involved = getattr(raw_event, "involved_object", None)
    return KubeEvent(
        reason=getattr(raw_event, "reason", "") or "",
        message=getattr(raw_event, "message", "") or "",
        kind=getattr(involved, "kind", None) if involved else None,
        name=getattr(involved, "name", None) if involved else None,
        namespace=namespace,
        event_type=getattr(raw_event, "type", "Warning") or "Warning",
        first_seen=_to_dt(getattr(raw_event, "first_timestamp", None)),
        last_seen=_event_time(raw_event),
        count=getattr(raw_event, "count", 1) or 1,
    )


def _event_to_alert(kev: KubeEvent, namespace: str) -> Alert:
    label_key = _KIND_TO_LABEL.get(kev.kind or "", "pod")
    return Alert(
        status="firing",
        labels={
            "alertname": f"K8sEvent{kev.reason}",
            "namespace": namespace,
            label_key: kev.name or "",
            "severity": "critical",
        },
        annotations={"description": kev.message or kev.reason},
        startsAt=kev.last_seen,
    )


def _event_time(raw_event):
    return (_to_dt(getattr(raw_event, "last_timestamp", None))
            or _to_dt(getattr(raw_event, "event_time", None))
            or _to_dt(getattr(raw_event, "first_timestamp", None)))


def _to_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
