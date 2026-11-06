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
from rca_agent.eval.capture import IncidentCaptureWriter
from rca_agent.graph.builder import GraphBuilder
from rca_agent.models.alert import Alert, KubeEvent
from rca_agent.models.incident import IncidentReport
from rca_agent.reasoning.flow import ReasoningFlow
from rca_agent.store.incident_store import IncidentStore

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
                flow_factory: Callable[[], ReasoningFlow],
                incident_store: IncidentStore | None = None) -> None:
        self.settings = settings
        self.builder = builder
        self._flow_factory = flow_factory
        # Durable store for write-through (Req 2). Optional so existing
        # callers/tests that construct the watcher without a DB keep working:
        # when None, _persist is a no-op and the watcher behaves exactly as
        # before. The app wires this in once the store is connected (see
        # webhook/app.py _startup_store).
        self._incident_store = incident_store
        self._seen_uids: OrderedDict[str, None] = OrderedDict()
        self.incidents: list[IncidentReport] = []
        # Status-based detection state: node_id -> consecutive-unhealthy count.
        self._unhealthy_streak: dict[str, int] = {}
        # node_ids already raised via status detection (cleared when healthy again).
        self._status_incident_open: set[str] = set()
        # Last poll's gate counters, surfaced by /debug/detection.
        self.last_diag: dict = {}
        # Incident capture for offline precision/recall labeling (OFF unless
        # settings.incident_capture_path is set). Best-effort; never raises.
        self.capture = IncidentCaptureWriter(
            settings.incident_capture_path,
            redact_logs=settings.incident_capture_redact_logs,
            include_graph=settings.incident_capture_include_graph,
            max_records=settings.incident_capture_max_records,
            graph_radius=settings.incident_capture_graph_radius,
        )

    def poll_once(self) -> list[IncidentReport]:
        """Run one polling cycle. Returns any newly-created incident reports."""
        kube = getattr(self.builder, "_kube", None)
        if kube is None:
            self.last_diag = {"status": "cluster client not built yet"}
            return []  # cluster client not built yet (first graph build still pending)

        ns = self.settings.namespace
        graph = self.builder.graph
        # Ignore events older than the configured window. Kubernetes stops
        # refreshing lastTimestamp on a long-ongoing fault, so a too-short
        # window makes the watcher blind to a still-active outage (see
        # config.event_max_age_minutes).
        cutoff = _now() - timedelta(minutes=max(1, self.settings.event_max_age_minutes))

        raw = _safe_list(lambda: kube.core.list_namespaced_event(ns), "events")
        # Diagnostics counters for this cycle.
        diag = {"events_seen": len(raw), "events_403": _EVENT_LIST_403["flag"],
                "matched_fault_reason": 0, "dropped_stale": 0, "out_of_scope": 0,
                "already_seen": 0, "event_incidents": 0, "status_incidents": 0}
        new_reports: list[IncidentReport] = []
        for raw_event in raw:
            kev = _to_kube_event(raw_event, ns)
            if kev.reason not in kev.FAULT_REASONS:
                continue
            diag["matched_fault_reason"] += 1
            if kev.last_seen and kev.last_seen < cutoff:
                diag["dropped_stale"] += 1
                continue
            if not kev.name or not graph.node(kev.name):
                diag["out_of_scope"] += 1
                continue  # out of scope: not a node the graph is monitoring

            uid = _event_uid(raw_event, kev)
            if uid in self._seen_uids:
                diag["already_seen"] += 1
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

            # Anchor dedup (0.7.0): if an incident for the same anchor is already
            # open in the window, merge this pod into it instead of creating a
            # duplicate (12 sibling pods failing the same way -> ONE incident).
            merged = self._merge_into_open_anchor(report, kev.name)
            if merged is not None:
                logger.info("event-watcher: merged %s into anchor incident %s",
                            kev.name, merged.incident_id)
                continue

            top = report.top_hypothesis
            logger.info(
                "event-watcher: auto-detected %s on %s -> incident %s (top=%s, confidence=%.2f)",
                kev.reason, kev.name, report.incident_id,
                top.cause if top else "none", top.confidence if top else 0.0,
            )
            self._store(report)
            new_reports.append(report)
            diag["event_incidents"] += 1

        # Fix B: status-based detection, independent of fresh events.
        new_reports.extend(self._detect_from_status(graph, ns, diag))

        # 0.7.3: flip recovered incidents to inactive (STRICT: all pods healthy).
        diag["resolved_now"] = self.reconcile_status(graph)

        diag["unhealthy_pods"] = sum(1 for _ in self._unhealthy_graph_pods(graph))
        self.last_diag = diag
        return new_reports

    def _pod_is_unhealthy(self, graph, pod_id: str) -> bool:
        """True if the pod is CURRENTLY unhealthy in the graph. A pod missing
        from the graph is treated as recovered (not unhealthy) — it is no longer
        a live fault signal (rolled out / deleted)."""
        attrs = graph.graph.nodes.get(pod_id)
        if not attrs:
            return False
        return attrs.get("healthy") is False or attrs.get("health") == "down"

    def reconcile_status(self, graph) -> int:
        """Flip active incidents to inactive once their fault clears.

        STRICT recovery: an incident becomes inactive only when EVERY pod in
        ``affected_pods`` is healthy again in the current graph (a pod removed
        from the graph counts as recovered). Pod-anchored incidents with no
        ``affected_pods`` fall back to their ``affected_resource``. Covers all
        incidents in the pool (event-, status- and webhook-sourced), not just
        status-detected ones. Returns how many were flipped this cycle.
        """
        flipped = 0
        for inc in self.incidents:
            if inc.status != "active":
                continue
            pods = inc.affected_pods or (
                [inc.affected_resource] if inc.affected_resource else [])
            if not pods:
                continue  # nothing to check against; leave active
            if any(self._pod_is_unhealthy(graph, p) for p in pods):
                continue  # at least one pod still unhealthy -> stays active
            inc.status = "inactive"
            inc.resolved_at = _now()
            # Persist the status/resolved_at flip so the durable record matches
            # the live store (Req 2.3) -- this is the exact field that must
            # survive a restart for the inactive tab.
            self._persist(inc)
            # Let it re-fire if it breaks again: clear status-detection latches.
            for p in pods:
                self._status_incident_open.discard(p)
                self._unhealthy_streak.pop(p, None)
            flipped += 1
            logger.info("event-watcher: incident %s resolved (all %d pod(s) healthy)",
                        inc.incident_id, len(pods))
        return flipped

    def _unhealthy_graph_pods(self, graph):
        """Yield (node_id, reason) for pod nodes currently marked unhealthy."""
        from rca_agent.graph.dependency_graph import NodeKind
        for nid, attrs in graph.graph.nodes(data=True):
            if attrs.get("kind") != NodeKind.pod.value:
                continue
            if attrs.get("healthy") is False or attrs.get("health") == "down":
                yield nid, attrs.get("health_reason", "unhealthy")

    def _detect_from_status(self, graph, ns: str, diag: dict) -> list[IncidentReport]:
        """Raise an incident for a pod that stays unhealthy across N consecutive
        rebuilds, even with no fresh K8s event. Survives Kubernetes aging
        events out from under a still-broken pod."""
        if not self.settings.status_detection_enabled:
            return []
        threshold = max(1, self.settings.status_unhealthy_rebuilds)
        current_unhealthy = dict(self._unhealthy_graph_pods(graph))

        # Reset streaks / clear open flags for pods that recovered.
        for nid in list(self._unhealthy_streak):
            if nid not in current_unhealthy:
                self._unhealthy_streak.pop(nid, None)
                self._status_incident_open.discard(nid)

        out: list[IncidentReport] = []
        for nid, reason in current_unhealthy.items():
            self._unhealthy_streak[nid] = self._unhealthy_streak.get(nid, 0) + 1
            if self._unhealthy_streak[nid] < threshold:
                continue
            if nid in self._status_incident_open:
                continue  # already raised; don't re-fire until it recovers
            self._status_incident_open.add(nid)
            alert = _status_to_alert(nid, reason, ns)
            try:
                report = self._flow_factory().run(alert)
            except Exception:
                logger.exception("event-watcher: status reasoning failed for %s", nid)
                continue
            logger.info(
                "event-watcher: status-detected persistently-unhealthy %s (%s) "
                "-> incident %s", nid, reason, report.incident_id)
            self._store(report)
            out.append(report)
            diag["status_incidents"] += 1
        return out

    def _remember(self, uid: str) -> None:
        self._seen_uids[uid] = None
        while len(self._seen_uids) > _MAX_SEEN_UIDS:
            self._seen_uids.popitem(last=False)

    def record_external_incident(self, report: IncidentReport) -> None:
        """Remember an incident diagnosed OUTSIDE the poll loop (i.e. a manual
        ``/webhook/alertmanager`` POST), so it shares the same ``/incidents``
        timeline and correlation pool as auto-detected ones. Safe to call for
        every report the webhook produces."""
        self._store(report, source="webhook")

    def _merge_into_open_anchor(self, report: IncidentReport,
                                pod_name: str) -> IncidentReport | None:
        """If a recent stored incident shares this report's anchor, merge the
        triggering pod into it (extend ``affected_pods``) and return it; else
        None. Anchor dedup (0.7.0): 12 sibling pods failing the same way become
        ONE anchor incident, not 12. Only applies to service/workload anchors —
        a pod-anchored incident (bare Job) has no siblings to merge."""
        anchor = report.affected_anchor
        if not anchor or report.anchor_kind not in ("service", "deployment"):
            return None
        window = max(60, self.settings.incident_correlation_window_minutes * 60)
        for other in reversed(self.incidents):
            if other.affected_anchor != anchor:
                continue
            delta = abs((report.created_at - other.created_at).total_seconds())
            if delta > window:
                continue
            if pod_name and pod_name not in other.affected_pods:
                other.affected_pods.append(pod_name)
                # affected_pods changed -> persist the updated merge target
                # (Req 2.4). Only when a merge actually mutated it.
                self._persist(other)
            return other
        return None

    def _persist(self, report: IncidentReport) -> None:
        """Write-through one incident to the durable store (Req 2).

        No-op when no store is wired (``self._incident_store is None``) so the
        watcher behaves exactly as before in tests/dev. The write is NON-FATAL
        (Req 5.3/5.4, Task 6.2): any failure is logged and swallowed so a DB
        outage never breaks the poll loop or the webhook request handler. The
        in-memory copy is kept and the next mutation re-persists, so memory and
        DB reconverge.

        Threading (D5): this runs the synchronous ``upsert`` inline, which is
        correct because every caller is already OFF the event loop --
        ``poll_once`` (and thus ``_store``/``reconcile_status``/``_correlate``/
        ``_merge_into_open_anchor``) runs inside ``asyncio.to_thread`` in the
        app, and ``record_external_incident`` runs in a synchronous FastAPI
        request handler. This keeps event_watcher.py import-light and sync; we
        deliberately do NOT introduce asyncio here.
        """
        if self._incident_store is None:
            return
        try:
            self._incident_store.upsert(report)
        except Exception:
            logger.warning(
                "event-watcher: failed to persist incident %s (non-fatal; "
                "keeping in-memory copy, will re-persist on next mutation)",
                report.incident_id, exc_info=True)

    def _store(self, report: IncidentReport, source: str = "event_watcher") -> None:
        self.incidents.append(report)
        if len(self.incidents) > _MAX_STORED_INCIDENTS:
            self.incidents.pop(0)
        self._correlate(report)
        # Durable write-through (Req 2.1/2.2): persist after the in-memory
        # append so the DB mirrors the live store for every create (event-,
        # status- and webhook-sourced). _correlate above may already have
        # persisted correlated incidents; re-persisting this one is harmless
        # (idempotent upsert on incident_id).
        self._persist(report)
        # Capture for later offline labeling (no-op unless configured).
        self.capture.record(report, source=source, graph=self.builder.graph)

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
            # Phase 3 (0.7.0): same-anchor siblings are already merged by
            # anchor-dedup, so correlation now links DIFFERENT anchors sharing
            # a failure signature (e.g. 5 different services all failing probes
            # at once) — a genuine cross-service pattern, not double-counting.
            if report.affected_anchor and other.affected_anchor and \
                    other.affected_anchor == report.affected_anchor:
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
                # related_incidents / suggested_next_steps changed -> persist
                # each affected incident so correlation notes are durable
                # (Req 2.4). Includes `report` itself; _store's own _persist is
                # an idempotent re-upsert.
                self._persist(r)

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
def _signature(report: IncidentReport) -> str | None:
    """A resource/anchor-independent fingerprint of the top hypothesis.

    Blanks out the affected resource, the anchor display, and each affected pod
    name inside the top hypothesis's ``cause``, so e.g. "<svc-A> failing health
    probe (HTTP 500)" and "<svc-B> failing health probe (HTTP 500)" compare
    equal while "<svc-A> OOMKilled" does not. This lets correlation (0.7.0)
    link DIFFERENT anchors that are failing the same way. Returns None when
    there's nothing to compare.
    """
    top = report.top_hypothesis
    if top is None:
        return None
    cause = top.cause
    tokens = [report.affected_resource, report.affected_anchor]
    tokens += list(report.affected_pods or [])
    replaced = False
    for tok in tokens:
        if tok and tok in cause:
            cause = cause.replace(tok, "<RESOURCE>")
            replaced = True
    return cause if replaced else None


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
        "NF-to-NF dependency edge yet to confirm or name it - treat this as a "
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
    _EVENT_LIST_403["flag"] = False
    try:
        result = call()
        return getattr(result, "items", None) or []
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "status", None)
        reason = getattr(exc, "reason", None) or type(exc).__name__
        if status == 403 or "forbidden" in str(reason).lower():
            _EVENT_LIST_403["flag"] = True
        logger.warning("event-watcher: skipping %s: cannot list (%s %s)",
                       label, status, reason)
        return []


# Set by _safe_list each cycle so poll_once's diagnostics can report whether
# the event list was forbidden (a 403) vs. genuinely empty.
_EVENT_LIST_403: dict = {"flag": False}


def _status_to_alert(node_id: str, reason: str, namespace: str):
    """Synthesize an Alert for a persistently-unhealthy graph pod (Fix B:
    status-based detection, no fresh K8s event required)."""
    return Alert(
        status="firing",
        labels={
            "alertname": "PodPersistentlyUnhealthy",
            "namespace": namespace,
            "pod": node_id,
            "severity": "critical",
        },
        annotations={"description":
                     f"Pod {node_id} has been unhealthy across multiple graph "
                     f"rebuilds: {reason} (status-based detection; no fresh "
                     f"Kubernetes event required)"},
        startsAt=_now(),
    )


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
