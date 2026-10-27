"""FastAPI application.

Endpoints:
  GET  /healthz            liveness
  GET  /readyz             readiness (graph built)
  GET  /graph/stats        current dependency-graph stats
  GET  /incidents          auto-detected incidents (event watcher)
  GET  /incidents/{id}     one auto-detected incident report in full
  POST /webhook/alertmanager  Alertmanager v4 webhook -> incident report(s)

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

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rca_agent import __version__
from rca_agent.config import get_settings
from rca_agent.detection.event_watcher import EventWatcher
from rca_agent.graph.builder import GraphBuilder
from rca_agent.models.alert import AlertmanagerPayload
from rca_agent.models.incident import IncidentReport
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
    build_task = asyncio.create_task(_initial_build())
    task = asyncio.create_task(_refresh_loop())
    watch_task = asyncio.create_task(_event_watch_loop())
    try:
        yield
    finally:
        for t in (build_task, task, watch_task):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t


app = FastAPI(title=settings.app_name, version=__version__, lifespan=_lifespan)


class WebhookResponse(BaseModel):
    received: int
    processed: int
    reports: list[IncidentReport]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/readyz")
def readyz() -> dict:
    ready = _flow is not None
    return {"status": "ready" if ready else "starting",
            "graph": _graph_builder.graph.stats()}


@app.get("/graph/stats")
def graph_stats() -> dict:
    return _graph_builder.graph.stats()


@app.get("/graph/pods")
def graph_pods() -> dict:
    """List pod nodes (id, display, health, component) for the viz dropdown."""
    pods = _graph_builder.graph.pods()
    return {"count": len(pods), "pods": pods}


@app.get("/graph/neighborhood/{node_id}")
def graph_neighborhood(node_id: str, radius: int = 1) -> dict:
    return _graph_builder.graph.neighborhood(node_id, radius=radius)


@app.get("/graph/view", response_class=HTMLResponse)
def graph_view(hide_orphans: bool = True) -> HTMLResponse:
    """Interactive HTML visualization of the full dependency graph.

    ``hide_orphans=true`` (default) drops edgeless nodes (unmounted
    secrets/configmaps). Pass ``?hide_orphans=false`` to see everything.
    """
    from rca_agent.graph.visualize import render_graph_html
    html = render_graph_html(_graph_builder.graph,
                             title=f"{settings.app_name} — dependency graph",
                             hide_orphans=hide_orphans)
    return HTMLResponse(content=html)


@app.get("/graph/view/{node_id}", response_class=HTMLResponse)
def graph_view_node(node_id: str, radius: int = 2,
                    hide_orphans: bool = False) -> HTMLResponse:
    """Interactive HTML visualization of one node's neighborhood."""
    from rca_agent.graph.visualize import render_neighborhood_html
    if not _graph_builder.graph.node(node_id):
        return HTMLResponse(content=f"<h3>Node '{node_id}' not found in graph.</h3>",
                            status_code=404)
    html = render_neighborhood_html(_graph_builder.graph, node_id, radius=radius,
                                    hide_orphans=hide_orphans)
    return HTMLResponse(content=html)


@app.get("/incidents")
def list_incidents(limit: int = 20) -> dict:
    """Incidents the event watcher auto-detected OR a human posted via the
    webhook, newest first — both paths share one timeline.

    Summary only (symptom/top-cause/confidence/related_count) — see
    ``/incidents/{id}`` for the full report with evidence chains, citations,
    and the ``related_incidents`` ids (incidents sharing this one's exact
    failure signature on a different resource within the correlation window
    — a pattern flag, not a claimed shared cause; see PLAN.md Known Issues).
    """
    incidents = list(reversed(_event_watcher.incidents))[:max(1, limit)]
    return {
        "count": len(incidents),
        "incidents": [
            {
                "incident_id": r.incident_id,
                "created_at": r.created_at,
                "symptom": r.symptom,
                "affected_resource": r.affected_resource,
                "severity": r.severity,
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


def main() -> None:
    """Console-script entry point (``rca-agent``)."""
    import uvicorn

    uvicorn.run("rca_agent.webhook.app:app", host=settings.host,
                port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
