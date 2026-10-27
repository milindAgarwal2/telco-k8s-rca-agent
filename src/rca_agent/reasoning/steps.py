"""The six deterministic reasoning steps.

Each step takes and mutates a :class:`ReasoningState`. They are plain functions
so they can be used both by the extractive pipeline and as LangGraph nodes.

Rules first, LLM second: these steps gather and score evidence deterministically.
The optional LLM step only re-ranks and explains what these produced; it can
never invent a cause that has no gathered evidence.
"""
from __future__ import annotations

from datetime import timedelta

from rca_agent.graph.dependency_graph import DependencyGraph
from rca_agent.models.incident import Citation, Evidence, Hypothesis
from rca_agent.rag.runbook_retriever import RunbookRetriever
from rca_agent.reasoning.state import ReasoningState
from rca_agent.tools.query_tools import QueryTools


def fence(text: str) -> str:
    """Fence untrusted text (logs, alert annotations) as data.

    Prompt-injection defense: a log line may carry injected instructions, so we
    wrap it in explicit data delimiters before it is ever shown to an LLM.
    """
    return f"<<UNTRUSTED_DATA>>{text}<<END_UNTRUSTED_DATA>>"


def triage(state: ReasoningState, cfg) -> ReasoningState:
    """Identify the affected resource and the fault time window from the alert."""
    alert = state.alert
    state.affected_resource = alert.target or state.affected_resource
    end = alert.starts_at or _utcnow()
    state.window_end = end
    state.window_start = end - timedelta(minutes=cfg.change_correlation_window_minutes)
    state.add_evidence(
        Evidence(
            category="event",
            summary=f"Alert '{alert.name}' fired for {state.affected_resource or 'unknown'}",
            resource=state.affected_resource,
            timestamp=alert.starts_at,
            citations=[Citation(kind="event", source=alert.name,
                                detail=alert.annotations.get("description", ""))],
        )
    )
    return state


def gather_evidence(state: ReasoningState, tools: QueryTools, cfg) -> ReasoningState:
    """Collect pod status, recent events, log tail and key metrics."""
    res = state.affected_resource
    if not res:
        return state
    ns = state.namespace

    status = tools.pod_status(res, ns)
    if not status.get("ready", True) or status.get("restart_count", 0) > 0:
        reason = status.get("last_termination_reason") or "not ready"
        state.add_evidence(Evidence(
            category="pod_status",
            summary=f"{res} unhealthy: {reason} (restarts={status.get('restart_count', 0)})",
            resource=res,
            citations=[Citation(kind="event", source=res, detail=reason)],
        ))

    for ev in tools.recent_events(res, ns, since_minutes=30):
        state.add_evidence(Evidence(
            category="event",
            summary=f"{ev.reason}: {ev.message}",
            resource=ev.name,
            timestamp=ev.last_seen,
            citations=[Citation(kind="event", source=ev.name or res, detail=ev.reason,
                                timestamp=ev.last_seen)],
        ))

    log_lines = tools.logs(res, ns, tail_lines=cfg.log_tail_lines)
    err_lines = [ln for ln in log_lines if "error" in ln.lower() or "fatal" in ln.lower()]
    for ln in err_lines[:5]:
        state.add_evidence(Evidence(
            category="log",
            summary=fence(ln),
            resource=res,
            citations=[Citation(kind="log", source=res, detail=ln[:120])],
        ))
    return state


def graph_walk(state: ReasoningState, graph: DependencyGraph) -> ReasoningState:
    """Upstream = candidate causes; downstream = blast radius."""
    res = state.affected_resource
    if not res or not graph.node(res):
        return state
    state.unhealthy_upstream = graph.unhealthy_upstream(res)
    state.blast_radius = graph.downstream(res)
    for up in state.unhealthy_upstream:
        node = graph.node(up) or {}
        # When `up` is a DIRECT calls-edge target (not a multi-hop one), cite
        # exactly which env var / ConfigMap key produced the dependency
        # (see graph/builder.py::_add_call_edges) instead of a generic
        # "upstream of" label.
        edge_evidence = graph.calls_edge_evidence(res, up)
        detail = f"upstream of {res} (via {edge_evidence})" if edge_evidence \
            else "upstream of " + res
        state.add_evidence(Evidence(
            category="graph",
            summary=f"Upstream dependency '{up}' is unhealthy "
                    f"({node.get('health_reason', 'unknown')})",
            resource=up,
            citations=[Citation(kind="graph", source=up, detail=detail)],
        ))
    if state.blast_radius:
        state.add_evidence(Evidence(
            category="graph",
            summary=f"Blast radius: {', '.join(state.blast_radius)}",
            resource=res,
            citations=[Citation(kind="graph", source=res, detail="downstream dependents")],
        ))
    return state


def change_correlation(state: ReasoningState, tools: QueryTools, cfg,
                       graph: DependencyGraph | None = None) -> ReasoningState:
    """List what changed shortly before the symptom — often the cheapest cause.

    To avoid flooding the report with unrelated edits, config/secret changes are
    correlated ONLY to objects the affected pod actually mounts (read from the
    graph's ``mounts`` edges). Rollouts/deployment changes that name the affected
    resource are always kept. When the graph has no mount info for the resource
    (e.g. an empty graph), we fall back to keeping all changes so we never hide a
    real signal — but we mark them as uncorrelated so ranking can weight them
    lower.
    """
    changes = tools.recent_changes(
        state.namespace, since_minutes=cfg.change_correlation_window_minutes
    )

    res = state.affected_resource
    mounted = graph.mounted_config(res) if (graph and res) else set()
    have_mount_info = bool(mounted)

    kept: list[dict] = []
    for ch in changes:
        ctype = str(ch.get("type", ""))
        obj = str(ch.get("object", ""))
        if ctype in ("configmap_update", "secret_update"):
            if have_mount_info:
                # Only keep config changes the affected pod actually consumes.
                if obj not in mounted:
                    continue
                ch["correlated"] = True
            else:
                ch["correlated"] = False  # no mount info -> weak correlation
        else:
            # rollout / deployment / scaling: keep, correlate if it names the res.
            ch["correlated"] = bool(res and (obj == res or (res and obj and obj in res)))
        kept.append(ch)

    state.changes = kept
    for ch in kept:
        ts = _to_dt(ch.get("at"))
        state.add_evidence(Evidence(
            category="change",
            summary=f"Recent {ch.get('type')} on {ch.get('object')}: {ch.get('detail', '')}",
            resource=ch.get("object"),
            timestamp=ts,
            citations=[Citation(kind="change", source=str(ch.get("object")),
                                detail=ch.get("detail", ""), timestamp=ts)],
        ))
    return state


def _to_dt(value):
    """Parse an ISO timestamp string to an aware datetime (None-safe)."""
    if not value:
        return None
    from datetime import datetime
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        from datetime import timezone
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def hypothesize_and_rank(state: ReasoningState) -> ReasoningState:
    """Build candidate causes from gathered evidence and score them.

    Deterministic scoring (no LLM). Each hypothesis must be tied to evidence;
    anything unsupported is never created. Scoring weights:
      +0.45  a fault event (OOMKilled/CrashLoop/etc.) on the resource or upstream
      +0.30  a recent change correlated in time
      +0.20  unhealthy upstream dependency (cascade)
      +0.15  error/fatal log lines
    """
    res = state.affected_resource or "unknown"
    candidates: dict[str, Hypothesis] = {}

    def ensure(key: str, cause: str) -> Hypothesis:
        if key not in candidates:
            candidates[key] = Hypothesis(cause=cause)
        return candidates[key]

    # 1) Fault events (pod_status/event evidence).
    fault_reasons = {"OOMKilled", "CrashLoopBackOff", "ImagePullBackOff",
                     "ErrImagePull", "Evicted"}
    for ev in state.evidence:
        reason = next((r for r in fault_reasons if r in ev.summary), None)
        if reason:
            h = ensure(f"fault:{ev.resource}:{reason}",
                       f"{ev.resource} {reason}")
            h.confidence += 0.45
            h.evidence_chain.append(f"{ev.resource} {reason}")
            h.supporting_evidence.append(ev)
            h.citations.extend(ev.citations)

    # 1b) Readiness / liveness probe failures. A pod that is Running but failing
    #     its probe (e.g. "Unhealthy: Readiness probe failed ... statuscode 500")
    #     is itself the fault — the app is up but unhealthy. This is a strong,
    #     self-contained signal, so it ranks at the top like other faults.
    probe = _detect_probe_failure(state)
    if probe is not None:
        ev, detail = probe
        h = ensure(f"probe:{ev.resource}", f"{ev.resource} failing health probe ({detail})")
        h.confidence += 0.50
        h.evidence_chain.append(f"{ev.resource} failing health probe: {detail}")
        h.supporting_evidence.append(ev)
        h.citations.extend(ev.citations)

    # 2) Recent changes correlated in time. A change the affected pod actually
    #    consumes (correlated=True) is a plausible cause; an uncorrelated change
    #    (no mount link) gets much lower weight so it cannot outrank the fault.
    for ch in state.changes:
        correlated = bool(ch.get("correlated"))
        h = ensure(f"change:{ch.get('object')}",
                   f"recent {ch.get('type')} to {ch.get('object')}")
        h.confidence += 0.30 if correlated else 0.05
        h.evidence_chain.append(
            f"{ch.get('type')} on {ch.get('object')}: {ch.get('detail', '')}"
            + ("" if correlated else " (not mounted by the affected pod)"))
        h.citations.append(Citation(kind="change", source=str(ch.get("object")),
                                    detail=ch.get("detail", "")))

    # 3) Unhealthy upstream (cascade causes).
    for up in state.unhealthy_upstream:
        h = ensure(f"upstream:{up}", f"{up} unhealthy (cascades to {res})")
        h.confidence += 0.20
        h.evidence_chain.append(f"{res} errors <- {up} unhealthy")

    # 4) Error logs add weak support to same-resource hypotheses.
    has_error_logs = any(e.category == "log" for e in state.evidence)
    if has_error_logs:
        for h in candidates.values():
            h.confidence += 0.15

    # Merge change + fault on the same object into a single causal chain.
    _link_change_to_fault(candidates, state)

    # Clamp and attach the symptom to the head of each chain.
    for h in candidates.values():
        h.confidence = min(h.confidence, 0.99)
        h.evidence_chain.insert(0, f"symptom: {state.alert.name} on {res}")

    state.hypotheses = sorted(candidates.values(),
                              key=lambda x: x.confidence, reverse=True)
    return state


def _detect_probe_failure(state) -> tuple | None:
    """Find a readiness/liveness probe failure for the affected resource.

    Returns ``(evidence, detail)`` for the strongest probe-failure signal, or
    None. Two sources count:
      * an ``Unhealthy`` event whose message mentions a readiness/liveness probe
        (the authoritative signal, e.g. "Readiness probe failed ... 500"), or
      * a ``pod_status`` evidence saying the pod is "not ready" with NO terminated
        fault reason (OOMKilled/CrashLoop are handled separately as faults).
    An explicit probe event is preferred over the generic not-ready status.
    """
    res = state.affected_resource
    probe_event = None
    not_ready = None
    for ev in state.evidence:
        s = ev.summary.lower()
        if ev.category == "event" and ("probe failed" in s or (
                "unhealthy" in s and "probe" in s)):
            probe_event = ev
        elif ev.category == "pod_status" and "not ready" in s and not any(
                r.lower() in s for r in (
                    "oomkilled", "crashloopbackoff", "imagepullbackoff",
                    "errimagepull", "evicted")):
            not_ready = ev
    if probe_event is not None:
        # Extract a short human detail from the event summary.
        detail = probe_event.summary.split(":", 1)[-1].strip() or "health probe failing"
        return probe_event, detail
    if not_ready is not None:
        return not_ready, f"{res} not ready (readiness probe failing)"
    return None


def _link_change_to_fault(candidates: dict, state) -> None:
    """If a CORRELATED change and a fault reference the affected pod, chain them.

    Models the headline example: ConfigMap memory-limit change -> OOMKilled.
    Only a change the affected pod actually consumes (correlated=True) is linked
    as a cause; uncorrelated namespace churn is never chained into the fault.
    """
    fault = next((h for k, h in candidates.items()
                  if k.startswith(("fault:", "probe:"))), None)
    correlated_objs = {str(ch.get("object")) for ch in state.changes
                       if ch.get("correlated")}
    change = next((h for k, h in candidates.items()
                   if k.startswith("change:")
                   and k.split("change:", 1)[1] in correlated_objs), None)
    if fault and change:
        fault.evidence_chain.extend(change.evidence_chain)
        fault.confidence = min(fault.confidence + 0.10, 0.99)
        fault.citations.extend(change.citations)


NO_RUNBOOK_SOURCE_NOTE = (
    "No runbook source is configured - no remediation guidance was retrieved "
    "from a knowledge base. The hypotheses and evidence above are the only "
    "cluster-derived findings; treat them accordingly."
)


def build_next_steps(state: ReasoningState, retriever: RunbookRetriever,
                     top_k: int) -> ReasoningState:
    """Pull human-facing next steps from runbooks via RAG (recommendations only).

    When the retriever finds nothing (most commonly ``NullRunbookRetriever``,
    the default when no runbook RAG URL is configured) we must not leave
    ``suggested_next_steps`` silently empty — that reads as "this incident has
    no guidance" when the real reason is "no runbook source is wired up". A
    single neutral note makes that distinction explicit instead of implying a
    finding that never happened.
    """
    top = state.hypotheses[0] if state.hypotheses else None
    query = top.cause if top else f"{state.alert.name} {state.affected_resource or ''}"
    hits = retriever.retrieve(query, top_k=top_k)
    if hits:
        state.suggested_next_steps = [
            f"{h.title}: {h.snippet} (see {h.source})" for h in hits
        ]
    else:
        state.suggested_next_steps = [NO_RUNBOOK_SOURCE_NOTE]
    return state


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
