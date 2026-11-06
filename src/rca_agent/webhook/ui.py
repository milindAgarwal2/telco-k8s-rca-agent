"""Server-rendered dashboard (FastAPI + Jinja2 + Bootstrap + HTMX).

Replaces the former Streamlit dashboard (dropped in 0.5.0 to cut the image by
the ~440 MB Streamlit/pyarrow/pandas stack -- see PLAN-image-size.md). Runs in
the SAME process as the backend, so it reads live data directly from the shared
objects (graph builder, event watcher, local runbook store, query log) with no
HTTP round-trip and no second container.

All routes are read-only except the runbook upload/delete and query-log clear,
which mutate only the agent's OWN local runbook store / in-memory log -- never
the cluster. The agent still has no write capability against Kubernetes.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# Mounted onto the app in app.py; name "ui_static" matches url_for in base.html.
_STATIC_DIR = _HERE / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)  # defensive: never crash import
static_files = StaticFiles(directory=str(_STATIC_DIR))

router = APIRouter()

_TAB_TEMPLATES = {
    "graph": "_graph.html",
    "incidents": "_incidents.html",
    "runbooks": "_runbooks.html",
    "querylog": "_querylog.html",
    "health": "_health.html",
}
_HEALTH_DOT = {"healthy": "🟢", "degraded": "🟠", "down": "🔴", "unknown": "⚪"}


def _root(request: Request) -> str:
    """Root path with trailing slash, honoring any proxy prefix."""
    return request.scope.get("root_path", "") + "/"


def init(app, *, graph_builder, event_watcher, local_store, query_log,
         settings, version: str) -> None:
    """Wire the UI into ``app``. Called once from app.py with the shared objects."""
    app.mount("/ui/static", static_files, name="ui_static")

    def _stats() -> dict:
        return graph_builder.graph.stats()

    def _incident_rows(status: str = "active") -> list[dict]:
        status = (status or "active").lower()
        if status not in ("active", "inactive", "all"):
            status = "active"
        incidents = list(reversed(event_watcher.incidents))  # newest first
        if status != "all":
            incidents = [r for r in incidents if r.status == status]
        incidents = incidents[:100]
        return [{
            "incident_id": r.incident_id,
            "created_at": str(r.created_at),
            "symptom": r.symptom,
            "affected_resource": r.affected_resource,
            "severity": getattr(r.severity, "value", r.severity),
            "status": r.status,
            "resolved_at": str(r.resolved_at) if r.resolved_at else None,
            "top_cause": r.top_hypothesis.cause if r.top_hypothesis else None,
            "confidence": r.top_hypothesis.confidence if r.top_hypothesis else 0.0,
            "related_count": len(r.related_incidents),
        } for r in incidents]

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(request, "base.html",
                                          {"active": "incidents", "root": _root(request)})

    @router.get("/ui/metrics", response_class=HTMLResponse)
    def metrics(request: Request):
        return templates.TemplateResponse(request, "_metrics.html", {"stats": _stats()})

    @router.get("/ui/tab/{tab}", response_class=HTMLResponse)
    def tab(request: Request, tab: str):
        name = _TAB_TEMPLATES.get(tab, "_incidents.html")
        ctx: dict = {"root": _root(request)}
        if tab == "graph":
            ctx["kind"] = "pod"
            ctx["nodes"] = graph_builder.graph.node_summaries(kind="pod")
            ctx["dot"] = _HEALTH_DOT
        elif tab == "runbooks":
            ctx["stats"] = local_store.stats()
        elif tab == "querylog":
            ctx["stats"] = query_log.stats()
        elif tab == "health":
            ctx.update(_health_ctx())
        return templates.TemplateResponse(request, name, ctx)

    # ---- graph node picker ----
    @router.get("/ui/graph/nodes", response_class=HTMLResponse)
    def graph_nodes_partial(request: Request, kind: str = "pod"):
        """Searchable node picker (datalist) for one kind, for the Graph tab's
        type selector to swap in via HTMX when the user changes Node/Service/Pod.
        """
        if kind not in ("node", "service", "pod"):
            kind = "pod"
        ctx = {
            "kind": kind,
            "nodes": graph_builder.graph.node_summaries(kind=kind),
            "dot": _HEALTH_DOT,
            "root": _root(request),
        }
        return templates.TemplateResponse(request, "_graph_picker.html", ctx)

    # ---- incidents ----
    @router.get("/ui/incidents/table", response_class=HTMLResponse)
    def inc_table(request: Request, status: str = "active"):
        return templates.TemplateResponse(request, "_incidents_table.html",
                                          {"incidents": _incident_rows(status),
                                           "status": status, "root": _root(request)})

    @router.get("/ui/incidents/{incident_id}", response_class=HTMLResponse)
    def inc_detail(request: Request, incident_id: str):
        report = event_watcher.get_incident(incident_id)
        if report is None:
            return HTMLResponse("<div class='alert alert-warning small'>Incident not found.</div>")
        # The template reads the incident's fields off the JSON-dumped report
        # dict ``d`` directly (``d.service_area``, ``d.potential_alarms``, ...),
        # so no per-field context key is wired here: both the service-area and
        # potential-alarms sections are populated purely by model_dump below.
        d = report.model_dump(mode="json")
        d["severity"] = getattr(report.severity, "value", report.severity)
        g = graph_builder.graph
        owners = g.owners(report.affected_resource) if report.affected_resource else {}
        # Per-pod health for the affected-pods block (service-anchored view).
        pod_health = []
        for p in (report.affected_pods or []):
            n = g.node(p) or {}
            pod_health.append({
                "id": p,
                "health": n.get("health", "unknown"),
                "reason": n.get("health_reason", ""),
            })
        # Anchor health rollup for the headline.
        anchor_node = g.node(report.affected_anchor) if report.affected_anchor else None
        anchor_health = (anchor_node or {}).get("health", "unknown")
        anchor_reason = (anchor_node or {}).get("health_reason", "")
        return templates.TemplateResponse(request, "_incident_detail.html",
                                          {"d": d, "owners": owners,
                                           "pod_health": pod_health,
                                           "anchor_health": anchor_health,
                                           "anchor_reason": anchor_reason,
                                           "root": _root(request)})

    @router.get("/ui/incidents/{incident_id}/pptx")
    def inc_pptx(incident_id: str):
        """On-demand RCA report deck (PPTX) for one incident."""
        from fastapi.responses import Response

        from rca_agent.webhook import pptx_report
        report = event_watcher.get_incident(incident_id)
        if report is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if not pptx_report.pptx_available():
            raise HTTPException(
                status_code=501,
                detail="PPTX export not installed in this build (pip install '.[pptx]').")
        owners = graph_builder.graph.owners(report.affected_resource) \
            if report.affected_resource else {}
        data = pptx_report.build_incident_pptx(report, owners)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition":
                     f'attachment; filename="RCA-{incident_id}.pptx"'})

    # ---- runbooks ----
    @router.get("/ui/runbooks/list", response_class=HTMLResponse)
    def rb_list(request: Request, msg: str = "", err: str = ""):
        docs = [asdict(d) for d in local_store.list_documents()]
        return templates.TemplateResponse(request, "_runbooks_list.html",
                                          {"docs": docs, "msg": msg, "err": err,
                                           "root": _root(request)})

    @router.post("/ui/runbooks/upload", response_class=HTMLResponse)
    async def rb_upload(request: Request, file: UploadFile = File(...)):  # noqa: B008
        from rca_agent.rag.local_store import extract_text
        msg, err = "", ""
        try:
            content = await file.read()
            name = file.filename or "runbook.txt"
            text = extract_text(name, content)
            if not text.strip():
                err = "No extractable text in uploaded file."
            else:
                doc = local_store.add_document(name, text)
                msg = f"Stored '{doc.name}' — {doc.chunk_count} chunk(s), {doc.chars} chars."
        except Exception as exc:  # noqa: BLE001
            err = f"Upload failed: {exc}"
        docs = [asdict(d) for d in local_store.list_documents()]
        return templates.TemplateResponse(request, "_runbooks_list.html",
                                          {"docs": docs, "msg": msg, "err": err,
                                           "root": _root(request)})

    @router.delete("/ui/runbooks/{name}", response_class=HTMLResponse)
    def rb_delete(request: Request, name: str):
        result = local_store.delete_document(name)
        msg = f"Deleted '{name}'." if result["deleted"] else ""
        err = "" if result["deleted"] else f"Runbook '{name}' not found."
        docs = [asdict(d) for d in local_store.list_documents()]
        return templates.TemplateResponse(request, "_runbooks_list.html",
                                          {"docs": docs, "msg": msg, "err": err,
                                           "root": _root(request)})

    # ---- query log ----
    @router.get("/ui/querylog/table", response_class=HTMLResponse)
    def ql_table(request: Request, neg: int = 0):
        entries = [asdict(e) for e in query_log.list_entries(limit=500)]
        if neg:
            entries = [e for e in entries if e["hit_count"] == 0]
        return templates.TemplateResponse(request, "_querylog_table.html",
                                          {"entries": entries, "root": _root(request)})

    @router.get("/ui/querylog/csv", response_class=PlainTextResponse)
    def ql_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Time", "Query", "Retriever", "Hits", "Matched runbooks"])
        for e in query_log.list_entries(limit=500):
            w.writerow([e.timestamp, e.query, e.retriever, e.hit_count,
                        ", ".join(e.hit_titles)])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition":
                                          "attachment; filename=runbook_query_log.csv"})

    @router.delete("/ui/querylog", response_class=HTMLResponse)
    def ql_clear(request: Request):
        query_log.clear()
        return templates.TemplateResponse(request, "_querylog_table.html",
                                          {"entries": [], "root": _root(request)})

    def _health_ctx() -> dict:
        health = {"status": "ok", "version": version}
        ready = {"status": "ready" if graph_builder.graph else "starting"}
        return {
            "health": health, "health_ok": True,
            "ready": ready, "ready_ok": ready["status"] == "ready",
            "stats_json": json.dumps(_stats(), indent=2, default=str),
        }

    app.include_router(router)
