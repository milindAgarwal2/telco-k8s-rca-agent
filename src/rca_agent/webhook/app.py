"""FastAPI application.

Endpoints:
  GET    /healthz            liveness
  GET    /readyz             readiness (graph built)
  GET    /graph/stats        current dependency-graph stats
  GET    /incidents          auto-detected incidents (event watcher)
  GET    /incidents/{id}     one auto-detected incident report in full
  POST   /webhook/alertmanager  Alertmanager v4 webhook -> incident report(s)
  POST   /runbooks           upload a runbook doc (.txt/.md/.pdf) for LocalRunbookRetriever
  GET    /runbooks           list uploaded runbook docs
  DELETE /runbooks/{name}    remove one uploaded runbook doc
  GET    /runbook-queries    runbook-retrieval attempt log (what was asked, hit/miss)
  DELETE /runbook-queries    clear the runbook-retrieval attempt log

The app builds the dependency graph once at startup (demo graph with no cluster)
and reuses it across requests. Each firing alert is reasoned about independently
and returned as an IncidentReport. A background event watcher polls the cluster
for fault-signal K8s events and runs the same reasoning entry point
automatically — see ``detection/event_watcher.py``.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rca_agent import __version__
from rca_agent.config import get_settings
from rca_agent.detection.event_watcher import EventWatcher
from rca_agent.graph.builder import GraphBuilder
from rca_agent.models.alert import AlertmanagerPayload
from rca_agent.models.incident import IncidentReport
from rca_agent.rag.local_store import extract_document, get_local_store
from rca_agent.rag.query_log import get_query_log
from rca_agent.reasoning.flow import ReasoningFlow

logger = logging.getLogger("rca_agent")

settings = get_settings()

# Shared state. Built eagerly at import so every endpoint (and the TestClient)
# has a graph. A cluster/kubeconfig failure here must NOT crash the process —
# we log it, serve an empty graph, and let the background loop retry.
_graph_builder = GraphBuilder(settings)


def _safe_rebuild() -> None:
    try:
        _graph_builder.rebuild()
    except Exception:
        logger.exception(
            "initial graph build failed (cluster/kubeconfig?); "
            "serving empty graph, will retry in the background"
        )


# Build eagerly ONLY when there is no cluster (the demo graph is instant and
# lets the TestClient/CI see a populated graph at import). A real cluster build
# can be slow against a large namespace, so it must NOT run synchronously at
# import or in the lifespan before ``yield`` — it would block uvicorn from
# accepting connections (no /healthz until the whole namespace is walked). The
# cluster build is kicked off in a background thread by the lifespan instead.
if not settings.cluster_enabled:
    _safe_rebuild()
_flow: ReasoningFlow = ReasoningFlow(settings, graph=_graph_builder.graph, builder=_graph_builder)

# ``flow_factory=lambda: _flow`` looks up the module-level ``_flow`` fresh on
# every poll — ``_initial_build``/``_refresh_loop`` reassign it via ``global``
# on each graph rebuild, so caching a reference here would go stale.
_event_watcher = EventWatcher(settings, _graph_builder, flow_factory=lambda: _flow)

# Shared with ExtractivePipeline via the same lru_cache-keyed args -- the
# Runbooks/Query-Log endpoints below read/write the exact same singletons the
# reasoning pipeline uses, so an upload through the dashboard is visible to
# the next incident's retrieval immediately.
_local_store = get_local_store(settings.runbook_store_path)
_query_log = get_query_log(settings.runbook_query_log_max_entries)

# Durable datastore (Store bundle: Database pool + IncidentStore + QueryLogStore).
# Constructed/connected/rehydrated in the lifespan startup (see _startup_store);
# endpoints (e.g. /readyz, Task 5.3) read this to report DB readiness. None until
# the lifespan has run its startup step.
_store = None


def _startup_store_construct() -> None:
    """Construct the durable store (FAST, synchronous) and wire write-through.

    Runs before the app serves traffic but does NOT connect to the DB -- it only
    builds the Store graph and injects the stores into EventWatcher/QueryLog so
    write-through is active. A missing ``RCA_DATABASE_URL`` raises
    ``ConfigurationError`` here (the intended fail-fast, Req 4.3). Connecting +
    schema + rehydrate are deferred to ``_startup_store_connect`` as a BACKGROUND
    task so an unreachable DB never blocks startup (same non-blocking principle
    as the initial graph build); ``/readyz`` reflects DB readiness once it
    connects.
    """
    global _store
    from rca_agent.store import get_store

    store = get_store()  # fail-fast on missing RCA_DATABASE_URL (Req 4.3)
    _store = store
    # Write-through wiring (Tasks 6/7): active immediately; persists are
    # non-fatal, so they simply no-op/log until the background connect succeeds.
    _event_watcher._incident_store = store.incidents
    _query_log._store = store.query_log


async def _startup_store_connect() -> None:
    """Background: connect to the DB, ensure schema, rehydrate the caches.

    Deferred off the startup path so a slow/unreachable DB does not block the
    app from serving (Req 5.1 non-fatal; the initial graph build uses the same
    background pattern). Rehydration (Req 3.1, 9.3) happens as soon as the DB is
    reachable; until then ``/incidents``/``/runbook-queries`` serve the
    in-memory caches and ``/readyz`` reports not-ready. All calls are blocking,
    so each runs in a worker thread (D5).
    """
    store = _store
    if store is None:
        return
    try:
        await asyncio.to_thread(store.db.connect_with_retry,
                                attempts=settings.db_connect_attempts,
                                max_delay=settings.db_connect_max_delay,
                                connect_timeout=settings.db_connect_timeout)
        await asyncio.to_thread(store.db.ensure_schema)

        # Rehydrate incidents (Req 3.1), newest-first from the DB inserted in
        # oldest-first order to match freshly-created incidents. Only when the
        # in-memory list is still empty so we never clobber live incidents.
        if not _event_watcher.incidents:
            recent = await asyncio.to_thread(store.incidents.load_recent, 200)
            _event_watcher.incidents[:] = list(reversed(recent))
            logger.info("rehydrated %d incident(s) from the datastore",
                        len(_event_watcher.incidents))

        # Rehydrate the runbook query log (Req 9.3).
        entries = await asyncio.to_thread(
            store.query_log.load_recent, settings.runbook_query_log_max_entries)
        _query_log.rehydrate(entries)
        logger.info("rehydrated %d runbook query-log entry(ies) from the datastore",
                    len(entries))
    except Exception:
        logger.exception(
            "datastore startup (connect/schema/rehydrate) failed; continuing "
            "with in-memory caches (DB is non-fatal; /readyz will reflect it)"
        )


async def _refresh_loop() -> None:
    """Periodically rebuild the dependency graph from the cluster.

    The blocking kube calls run in a thread so the event loop stays responsive.
    ``GraphBuilder.rebuild`` swaps ``_graph_builder._graph`` atomically, so read
    endpoints never observe a half-built graph. Errors are logged, not fatal.
    """
    interval = max(5, settings.graph_rebuild_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_graph_builder.rebuild)
            logger.debug("graph refreshed: %s", _graph_builder.graph.stats())
        except Exception:
            logger.exception("graph refresh failed; keeping previous graph")


async def _event_watch_loop() -> None:
    """Periodically poll the cluster for fault-signal events (Phase 1:
    automatic detection, so a human doesn't have to hand-craft a webhook
    payload for every red pod). No-op in demo/stub mode — there are no real
    K8s events to watch without a cluster.
    """
    if not (settings.cluster_enabled and settings.event_watch_enabled):
        logger.info("event watcher disabled (cluster_enabled=%s event_watch_enabled=%s)",
                    settings.cluster_enabled, settings.event_watch_enabled)
        return
    interval = max(5, settings.event_watch_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            new_reports = await asyncio.to_thread(_event_watcher.poll_once)
            if new_reports:
                logger.info("event-watcher: %d new incident(s) this cycle", len(new_reports))
        except Exception:
            logger.exception("event-watcher poll failed; will retry next cycle")


@asynccontextmanager
async def _lifespan(_: FastAPI):
    logging.basicConfig(level=settings.log_level)
    # Kick off the first graph build WITHOUT blocking startup. A large-namespace
    # cluster build can take a while; running it synchronously here would stop
    # uvicorn from serving /healthz until it finished (and could look like a
    # hang). We build in a background thread and let the refresh loop keep it
    # fresh. With no cluster, this is the instant demo graph.
    async def _initial_build() -> None:
        await asyncio.to_thread(_safe_rebuild)
        global _flow
        _flow = ReasoningFlow(settings, graph=_graph_builder.graph,
                              builder=_graph_builder)
        logger.info("rca-agent initial graph built: %s",
                    _graph_builder.graph.stats())

    logger.info("rca-agent starting: mode=%s cluster=%s (initial graph build "
                "running in background)",
                settings.reasoning_mode, settings.cluster_enabled)
    # Construct the durable store synchronously (FAST): this fails fast on a
    # missing RCA_DATABASE_URL (Req 4.3) and wires write-through, but does NOT
    # connect -- so an unreachable DB cannot block startup. The connect + schema
    # + rehydrate run in the background (like the initial graph build); /readyz
    # reflects DB readiness as it completes.
    _startup_store_construct()
    store_task = asyncio.create_task(_startup_store_connect())
    build_task = asyncio.create_task(_initial_build())
    task = asyncio.create_task(_refresh_loop())
    watch_task = asyncio.create_task(_event_watch_loop())
    try:
        yield
    finally:
        for t in (store_task, build_task, task, watch_task):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t


app = FastAPI(title=settings.app_name, version=__version__, lifespan=_lifespan)

# Server-rendered dashboard (replaces the former Streamlit UI; same process,
# reads the shared objects directly). Served at "/" and "/ui/*".
from rca_agent.webhook import ui as _ui

_ui.init(app, graph_builder=_graph_builder, event_watcher=_event_watcher,
         local_store=_local_store, query_log=_query_log,
         settings=settings, version=__version__)


class WebhookResponse(BaseModel):
    received: int
    processed: int
    reports: list[IncidentReport]


@app.get("/healthz")
def healthz() -> dict:
    # Liveness MUST stay independent of the database (Req 5.2): a transient DB
    # outage must not fail liveness, or Kubernetes would kill and restart the
    # pod in a loop instead of letting it ride out the outage. DB readiness is
    # reported by /readyz below, not here.
    return {"status": "ok", "version": __version__}


@app.get("/readyz")
def readyz() -> dict:
    # Readiness requires BOTH the reasoning flow/graph being up AND the durable
    # datastore being connected (Req 5.1): the DB is mandatory (D1), so it is
    # legitimately part of readiness. _store is None until the lifespan startup
    # runs, so guard access before calling is_ready().
    db_ready = _store is not None and _store.db.is_ready()
    ready = (_flow is not None) and db_ready
    return {"status": "ready" if ready else "starting",
            "graph": _graph_builder.graph.stats(),
            "database": "ready" if db_ready else "not-ready"}


@app.get("/graph/stats")
def graph_stats() -> dict:
    return _graph_builder.graph.stats()


@app.get("/debug/detection")
def debug_detection() -> dict:
    """Why incidents are/aren't being auto-detected — exposes every gate in the
    event watcher's last poll cycle, so 'no incidents' is self-diagnosing.

    Counters (last cycle): events_seen, events_403 (event list forbidden),
    matched_fault_reason, dropped_stale (older than event_max_age_minutes),
    out_of_scope (not a graph node), already_seen (deduped), event_incidents,
    status_incidents, unhealthy_pods (currently unhealthy in the graph).
    """
    return {
        "cluster_enabled": settings.cluster_enabled,
        "event_watch_enabled": settings.event_watch_enabled,
        "status_detection_enabled": settings.status_detection_enabled,
        "event_max_age_minutes": settings.event_max_age_minutes,
        "status_unhealthy_rebuilds": settings.status_unhealthy_rebuilds,
        "last_poll": _event_watcher.last_diag,
        "total_incidents": len(_event_watcher.incidents),
    }


@app.get("/graph/pods")
def graph_pods() -> dict:
    """List pod nodes (id, display, health, component) for the viz dropdown."""
    pods = _graph_builder.graph.pods()
    return {"count": len(pods), "pods": pods}


# Node kinds the Graph-tab picker exposes. Restricted to the three the user
# navigates by; other kinds (configmap/secret/pvc/...) are reachable only as
# neighbors of these, not as top-level picker entries.
_PICKER_KINDS = ("node", "service", "pod")


@app.get("/graph/nodes")
def graph_nodes(kind: str = "pod") -> dict:
    """List graph nodes of one ``kind`` for the viz picker.

    ``kind`` is one of ``node`` (K8s worker node), ``service`` or ``pod``
    (default). Returns ``{kind, count, nodes:[{id,display,health,kind,
    component}]}`` sorted by display name — the searchable type-filtered
    picker in the Graph tab consumes this.
    """
    if kind not in _PICKER_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {_PICKER_KINDS}, got '{kind}'")
    nodes = _graph_builder.graph.node_summaries(kind=kind)
    return {"kind": kind, "count": len(nodes), "nodes": nodes}


@app.get("/graph/neighborhood/{node_id:path}")
def graph_neighborhood(node_id: str, radius: int = 1) -> dict:
    return _graph_builder.graph.neighborhood(node_id, radius=radius)


def _incident_index() -> dict:
    """Map node_id -> incident_id so the graph can link an unhealthy pod to its
    incident (Task 2). Prefers ACTIVE incidents; a pod in affected_pods (or the
    incident's affected_resource) points at that incident. Newest wins."""
    index: dict[str, str] = {}
    for r in _event_watcher.incidents:  # oldest->newest; newest overwrites
        if r.status != "active":
            continue
        targets = list(r.affected_pods or [])
        if r.affected_resource:
            targets.append(r.affected_resource)
        for t in targets:
            index[t] = r.incident_id
    return index


@app.get("/graph/view", response_class=HTMLResponse)
def graph_view(hide_orphans: bool = True, with_pod_filter: bool = True) -> HTMLResponse:
    """Interactive HTML visualization of the full dependency graph.

    ``hide_orphans=true`` (default) drops edgeless nodes (unmounted
    secrets/configmaps). Pass ``?hide_orphans=false`` to see everything.
    ``with_pod_filter=true`` (default) overlays this page's own pod picker;
    pass ``?with_pod_filter=false`` when embedding this HTML inside another
    UI (e.g. the Streamlit dashboard) that already provides its own selector,
    so there's only one control driving which pod is shown.
    """
    from rca_agent.graph.visualize import render_graph_html
    html = render_graph_html(_graph_builder.graph,
                             title=f"{settings.app_name} — dependency graph",
                             hide_orphans=hide_orphans,
                             with_pod_filter=with_pod_filter,
                             incident_index=_incident_index())
    return HTMLResponse(content=html)


@app.get("/graph/view/{node_id:path}", response_class=HTMLResponse)
def graph_view_node(node_id: str, radius: int = 2,
                    hide_orphans: bool = False, with_pod_filter: bool = True) -> HTMLResponse:
    """Interactive HTML visualization of one node's neighborhood.

    See ``/graph/view`` for ``with_pod_filter``.
    """
    from rca_agent.graph.visualize import render_neighborhood_html
    if not _graph_builder.graph.node(node_id):
        return HTMLResponse(content=f"<h3>Node '{node_id}' not found in graph.</h3>",
                            status_code=404)
    html = render_neighborhood_html(_graph_builder.graph, node_id, radius=radius,
                                    hide_orphans=hide_orphans,
                                    with_pod_filter=with_pod_filter,
                                    incident_index=_incident_index())
    return HTMLResponse(content=html)


@app.get("/incidents")
def list_incidents(limit: int = 20, status: str = "active") -> dict:
    """Incidents the event watcher auto-detected OR a human posted via the
    webhook, newest first — both paths share one timeline.

    ``status`` filters by lifecycle (0.7.3): ``active`` (default — still
    unhealthy), ``inactive`` (recovered: all affected pods healthy again) or
    ``all``. An incident flips to inactive STRICTLY — only when every pod in
    ``affected_pods`` is healthy in the current graph.

    Summary only (symptom/top-cause/confidence/related_count/status) — see
    ``/incidents/{id}`` for the full report with evidence chains, citations,
    and the ``related_incidents`` ids (incidents sharing this one's exact
    failure signature on a different resource within the correlation window
    — a pattern flag, not a claimed shared cause; see PLAN.md Known Issues).
    """
    status = status.lower()
    if status not in ("active", "inactive", "all"):
        raise HTTPException(
            status_code=400,
            detail="status must be one of 'active', 'inactive', 'all'")
    incidents = list(reversed(_event_watcher.incidents))  # newest first
    if status != "all":
        incidents = [r for r in incidents if r.status == status]
    incidents = incidents[:max(1, limit)]
    return {
        "count": len(incidents),
        "status": status,
        "incidents": [
            {
                "incident_id": r.incident_id,
                "created_at": r.created_at,
                "symptom": r.symptom,
                "affected_resource": r.affected_resource,
                "severity": r.severity,
                "status": r.status,
                "resolved_at": r.resolved_at,
                "top_cause": r.top_hypothesis.cause if r.top_hypothesis else None,
                "confidence": r.top_hypothesis.confidence if r.top_hypothesis else None,
                "related_count": len(r.related_incidents),
            }
            for r in incidents
        ],
    }


@app.get("/incidents/{incident_id}", response_model=IncidentReport)
def get_incident(incident_id: str) -> IncidentReport:
    report = _event_watcher.get_incident(incident_id)
    # Durable fallback (Req 8.3): the in-memory cache is capped at 200 incidents,
    # so an older id that has aged out of the cache still resolves from the DB.
    # Guard _store (None before startup) and gate on is_ready() to avoid a DB
    # call when not connected; a lookup failure is non-fatal (Req 5.3) -- log and
    # leave report None so we still return the same 404 shape.
    if report is None and _store is not None and _store.db.is_ready():
        try:
            report = _store.incidents.get(incident_id)
        except Exception:
            logger.warning("durable incident lookup for '%s' failed; "
                           "serving from in-memory cache only", incident_id,
                           exc_info=True)
    if report is None:
        raise HTTPException(status_code=404, detail=f"incident '{incident_id}' not found")
    return report


@app.post("/webhook/alertmanager", response_model=WebhookResponse)
def alertmanager_webhook(payload: AlertmanagerPayload) -> WebhookResponse:
    flow = _flow or ReasoningFlow(settings, graph=_graph_builder.graph, builder=_graph_builder)
    firing = [a for a in payload.alerts if a.status == "firing"]
    reports = [flow.run(alert) for alert in firing]
    for report in reports:
        # Share the event watcher's incident pool so a manually-posted alert
        # still participates in correlation against auto-detected incidents
        # (and shows up in GET /incidents).
        _event_watcher.record_external_incident(report)
    logger.info("processed %d/%d firing alerts", len(reports), len(payload.alerts))
    return WebhookResponse(received=len(payload.alerts),
                           processed=len(reports), reports=reports)


@app.post("/runbooks")
async def upload_runbook(file: UploadFile = File(...)) -> dict:  # noqa: B008
    """Upload a runbook document (``.txt``/``.md``/``.pdf``) for
    ``LocalRunbookRetriever``. Re-uploading the same filename replaces its
    chunks (a safe overwrite, not a duplicate) -- see
    ``LocalRunbookStore.add_document``.
    """
    content = await file.read()
    name = file.filename or "runbook.txt"
    import os
    import re as _re
    # Per-document asset dir (sanitized name) for extracted page images.
    safe = _re.sub(r"[^A-Za-z0-9._-]", "_", os.path.splitext(name)[0]) or "runbook"
    asset_dir = os.path.join(settings.runbook_asset_dir, safe)
    try:
        text, images = extract_document(name, content, asset_dir=asset_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="no extractable text in uploaded file")
    doc = _local_store.add_document(name, text, images=images)
    return asdict(doc)


@app.get("/runbooks")
def list_runbooks() -> dict:
    docs = _local_store.list_documents()
    return {"count": len(docs), "documents": [asdict(d) for d in docs], "stats": _local_store.stats()}


@app.delete("/runbooks/{name}")
def delete_runbook(name: str) -> dict:
    result = _local_store.delete_document(name)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail=f"runbook '{name}' not found")
    return result


@app.get("/runbook-queries")
def list_runbook_queries(limit: int = 100) -> dict:
    """The runbook-retrieval attempt log: what was asked, and whether
    anything matched. A zero-``hit_count`` entry is the signal for "write a
    runbook for this."
    """
    entries = _query_log.list_entries(limit=limit)
    return {"stats": _query_log.stats(), "entries": [asdict(e) for e in entries]}


@app.delete("/runbook-queries")
def clear_runbook_queries() -> dict:
    return {"cleared": _query_log.clear()}


def main() -> None:
    """Console-script entry point (``rca-agent``)."""
    import uvicorn

    uvicorn.run("rca_agent.webhook.app:app", host=settings.host,
                port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
