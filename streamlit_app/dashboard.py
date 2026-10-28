"""Streamlit dashboard for the read-only K8s RCA agent.

The ONLY externally-published process (see ``docker/entrypoint.sh`` — it
binds ``$RCA_PORT`` directly). It talks to the FastAPI backend over a Unix
domain socket, NOT a TCP port — this image runs with ``--network host``
(see deploy-cobra.sh), which shares the host's network namespace, so a
"127.0.0.1-only" port would still be reachable by every other process on
that shared jumpserver. A UDS is a path in this container's own filesystem
namespace, which ``--network host`` does not share, so nothing outside this
container can reach the backend — the published port is the only way in,
same-host or not. It never queries the cluster directly; it only reads the
backend's already-read-only JSON/HTML endpoints (``/incidents``,
``/graph/stats``, ``/graph/pods``, ``/graph/view``). This process has no
write capability of any kind, same as the rest of the agent.

Layout: one top metrics row (always visible), then five tabs:
  Graph       -- the live dependency graph, embedded from /graph/view(/{node}).
                 One pod selector lives here (in Streamlit); the embedded
                 page's own built-in picker is turned off via
                 ?with_pod_filter=false so there's only one control.
  Incidents   -- the incident list + full report detail (hypotheses,
                 evidence, citations, correlation, suggested next steps).
  Runbooks    -- upload/list/delete documents for LocalRunbookRetriever
                 (local keyword/rarity matching, no embeddings/LLM).
  Query Log   -- every runbook-retrieval attempt, hit or miss -- the signal
                 for which runbooks to write next.
  Health      -- /healthz, /readyz, version, raw /graph/stats.
"""
from __future__ import annotations

import csv
import io
import os

import httpx
import streamlit as st
import streamlit.components.v1 as components

UDS_PATH = os.environ.get("RCA_BACKEND_UDS", "/tmp/rca-agent.sock")
# The host in this base URL is never actually resolved/connected to -- the
# UDS transport below redirects every request through the socket file
# instead. It only needs to be a syntactically valid URL for httpx.
_BACKEND_BASE_URL = "http://backend"


def _client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.HTTPTransport(uds=UDS_PATH),
        base_url=_BACKEND_BASE_URL,
    )


st.set_page_config(page_title="RCA Agent", page_icon="🩺", layout="wide")

_SEVERITY_BADGE = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
_HEALTH_DOT = {"healthy": "🟢", "degraded": "🟠", "down": "🔴", "unknown": "⚪"}


@st.cache_data(ttl=5)
def _get_json(path: str) -> dict:
    with _client() as client:
        resp = client.get(path, timeout=10)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=5)
def _get_html(path: str) -> str:
    with _client() as client:
        resp = client.get(path, timeout=15)
    resp.raise_for_status()
    return resp.text


def _post_runbook(filename: str, content: bytes, content_type: str) -> dict:
    """Not cached -- a mutation, unlike ``_get_json``/``_get_html``."""
    with _client() as client:
        resp = client.post(
            "/runbooks",
            files={"file": (filename, content, content_type or "application/octet-stream")},
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


def _delete(path: str) -> dict:
    """Not cached -- a mutation, unlike ``_get_json``/``_get_html``."""
    with _client() as client:
        resp = client.delete(path, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _severity_badge(sev: str) -> str:
    return f"{_SEVERITY_BADGE.get(sev, '⚪')} {sev}"


def main() -> None:
    st.title("🩺 Kubernetes Fault Detection & Root-Cause Agent")
    st.caption(
        "Read-only — this dashboard only reads data the agent already "
        "gathered via get/list/watch. It has no write capability."
    )

    top_col, refresh_col = st.columns([6, 1])
    with refresh_col:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    try:
        stats = _get_json("/graph/stats")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not reach the backend over {UDS_PATH}: {exc}")
        return

    with top_col:
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Graph nodes", stats.get("nodes", 0))
        s2.metric("Graph edges", stats.get("edges", 0))
        s3.metric("Changes tracked", stats.get("changes", 0))
        s4.metric("Last rebuilt", (stats.get("last_rebuilt") or "—")[:19])

    tab_graph, tab_incidents, tab_runbooks, tab_query_log, tab_health = st.tabs(
        ["🕸️ Graph", "🩺 Incidents", "📝 Runbooks", "📊 Query Log", "⚙️ Health"]
    )

    with tab_graph:
        _render_graph_tab()
    with tab_incidents:
        _render_incidents_tab()
    with tab_runbooks:
        _render_runbooks_tab()
    with tab_query_log:
        _render_query_log_tab()
    with tab_health:
        _render_health_tab(stats)


def _render_graph_tab() -> None:
    try:
        pods = _get_json("/graph/pods").get("pods", [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load the pod list: {exc}")
        return

    options = {"— show full graph —": None}
    for p in sorted(pods, key=lambda p: str(p.get("display", p["id"])).lower()):
        dot = _HEALTH_DOT.get(p.get("health"), "⚪")
        options[f"{dot} {p.get('display', p['id'])}"] = p["id"]

    col1, col2 = st.columns([4, 1])
    with col1:
        choice = st.selectbox("Pod / resource", list(options.keys()))
    with col2:
        radius = st.selectbox("Radius", [1, 2, 3], index=1)

    node_id = options[choice]
    path = (
        "/graph/view?with_pod_filter=false"
        if node_id is None
        else f"/graph/view/{node_id}?radius={radius}&with_pod_filter=false"
    )

    try:
        html = _get_html(path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load the graph view: {exc}")
        return

    components.html(html, height=800, scrolling=True)


def _render_incidents_tab() -> None:
    st.subheader("Incidents")

    try:
        data = _get_json("/incidents?limit=100")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load incidents: {exc}")
        return

    incidents = data.get("incidents", [])
    if not incidents:
        st.info(
            "No incidents yet. Either nothing is currently unhealthy, or "
            "the event watcher hasn't found anything yet (in demo/no-cluster "
            "mode, there are no real incidents until one is posted to "
            "/webhook/alertmanager)."
        )
        return

    rows = [
        {
            "Severity": _severity_badge(i.get("severity", "")),
            "Symptom": i.get("symptom", ""),
            "Resource": i.get("affected_resource", ""),
            "Top cause": i.get("top_cause") or "—",
            "Confidence": f"{(i.get('confidence') or 0) * 100:.0f}%",
            "Related": i.get("related_count", 0),
            "Created": (i.get("created_at") or "")[:19],
            "id": i["incident_id"],
        }
        for i in incidents
    ]
    st.dataframe(
        [{k: v for k, v in r.items() if k != "id"} for r in rows],
        use_container_width=True,
        hide_index=True,
    )

    options = {f"{r['Symptom']}  ({r['id']})": r["id"] for r in rows}
    choice = st.selectbox("Inspect an incident", list(options.keys()))
    if choice:
        _render_incident_detail(options[choice])


def _render_incident_detail(incident_id: str) -> None:
    report = _get_json(f"/incidents/{incident_id}")

    st.markdown(f"### {report['symptom']}")
    st.caption(
        f"Resource: `{report.get('affected_resource')}` · "
        f"Severity: {_severity_badge(report.get('severity', ''))} · "
        f"Created: {(report.get('created_at') or '')[:19]}"
    )

    hyps = report.get("hypotheses", [])
    if hyps:
        st.markdown("#### Ranked hypotheses")
        for h in hyps:
            conf = h.get("confidence", 0.0)
            st.progress(
                min(max(conf, 0.0), 1.0),
                text=f"{h['cause']}  —  {conf * 100:.0f}% confidence",
            )
            with st.expander("Evidence chain & citations"):
                for step in h.get("evidence_chain", []):
                    st.markdown(f"- {step}")
                for c in h.get("citations", []):
                    st.caption(f"[{c.get('kind')}] {c.get('source')} — {c.get('detail', '')}")

    related = report.get("related_incidents", [])
    if related:
        st.markdown(f"#### Correlated with {len(related)} other incident(s)")
        st.caption(
            "Same failure signature on a different resource within the "
            "correlation window — a pattern flag, not a verified shared cause."
        )
        st.code(", ".join(related), language=None)

    steps = report.get("suggested_next_steps", [])
    if steps:
        st.markdown("#### Suggested next steps")
        for s in steps:
            if s.startswith("Correlated:"):
                st.warning(s)
            elif s.startswith("No runbook source"):
                st.caption(s)
            else:
                st.info(s)

    evidence = report.get("evidence", [])
    if evidence:
        with st.expander(f"Full evidence ({len(evidence)} item(s))"):
            for e in evidence:
                st.markdown(f"**[{e.get('category')}]** {e.get('summary')}")


def _render_runbooks_tab() -> None:
    st.subheader("Runbooks")
    st.caption(
        "Upload remediation runbooks (.txt / .md / .pdf) for "
        "LocalRunbookRetriever — fully local keyword/rarity matching "
        "(no embeddings, no vector DB, no external LLM). Separate from, and "
        "doesn't replace, the still-unbuilt HTTP doc-intelligence retriever. "
        "See the Query Log tab to see what's being asked and whether "
        "anything matches — the signal for which runbooks to write next."
    )

    try:
        data = _get_json("/runbooks")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load runbooks: {exc}")
        return

    docs = data.get("documents", [])
    doc_stats = data.get("stats", {})
    m1, m2 = st.columns(2)
    m1.metric("Documents", doc_stats.get("documents", 0))
    m2.metric("Chunks", doc_stats.get("chunks", 0))

    st.markdown("#### Upload a runbook")
    uploaded = st.file_uploader(
        "Runbook file", type=["txt", "md", "pdf"], key="runbook_uploader"
    )
    if uploaded is not None and st.button("📤 Upload"):
        with st.spinner(f"Processing {uploaded.name}..."):
            try:
                result = _post_runbook(uploaded.name, uploaded.getvalue(), uploaded.type)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Upload failed: {exc}")
            else:
                st.success(
                    f"Stored '{result['name']}' — {result['chunk_count']} "
                    f"chunk(s), {result['chars']} chars."
                )
                st.cache_data.clear()
                st.rerun()

    st.markdown("#### Uploaded documents")
    if not docs:
        st.info(
            "No runbooks uploaded yet. Until one is uploaded, incident "
            "reports show a neutral 'no runbook source configured' note "
            "instead of guessing at remediation steps."
        )
        return

    for d in sorted(docs, key=lambda d: d.get("added_at", ""), reverse=True):
        name = d["name"]
        c1, c2, c3, c4 = st.columns([3, 1, 2, 1])
        c1.markdown(f"**{name}**")
        c2.caption(f"{d.get('chunk_count', 0)} chunk(s)")
        c3.caption((d.get("added_at") or "")[:19])
        confirm_key = f"confirm_delete_runbook_{name}"
        if c4.button("🗑️ Delete", key=f"delete_runbook_{name}"):
            st.session_state[confirm_key] = True
        if st.session_state.get(confirm_key):
            st.warning(f"Delete '{name}'? This cannot be undone.")
            cc1, cc2 = st.columns(2)
            if cc1.button("Confirm delete", key=f"confirm_runbook_{name}"):
                try:
                    _delete(f"/runbooks/{name}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Delete failed: {exc}")
                else:
                    st.session_state.pop(confirm_key, None)
                    st.cache_data.clear()
                    st.rerun()
            if cc2.button("Cancel", key=f"cancel_runbook_{name}"):
                st.session_state.pop(confirm_key, None)
                st.rerun()


def _render_query_log_tab() -> None:
    st.subheader("Runbook Query Log")
    st.caption(
        "Every runbook-retrieval attempt made while building an incident's "
        "suggested next steps. Not LLM calls — this project has no LLM call "
        "anywhere in the default extractive pipeline. A zero-hit "
        "('negative') entry is the signal for 'write a runbook for this.'"
    )

    try:
        data = _get_json("/runbook-queries?limit=500")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load the query log: {exc}")
        return

    log_stats = data.get("stats", {})
    entries = data.get("entries", [])

    m1, m2, m3, m4 = st.columns(4)
    total = log_stats.get("total", 0)
    m1.metric("Total queries", total)
    m2.metric("Matched (positive)", log_stats.get("positive", 0))
    m3.metric("No match (negative)", log_stats.get("negative", 0))
    hit_rate = f"{(log_stats.get('positive', 0) / total * 100):.0f}%" if total else "—"
    m4.metric("Hit rate", hit_rate)

    if not entries:
        st.info("No runbook queries recorded yet.")
        return

    show_only_negative = st.checkbox("Show only no-match (negative) queries", value=False)
    filtered = [e for e in entries if e.get("hit_count", 0) == 0] if show_only_negative else entries

    rows = [
        {
            "Time": (e.get("timestamp") or "")[:19],
            "Query": e.get("query", ""),
            "Retriever": e.get("retriever", ""),
            "Hits": e.get("hit_count", 0),
            "Matched runbooks": ", ".join(e.get("hit_titles") or []) or "—",
        }
        for e in filtered
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=["Time", "Query", "Retriever", "Hits", "Matched runbooks"]
    )
    writer.writeheader()
    writer.writerows(rows)
    st.download_button(
        "⬇️ Download CSV", buf.getvalue(),
        file_name="runbook_query_log.csv", mime="text/csv",
    )

    st.markdown("#### Maintenance")
    confirm_clear = st.checkbox(
        "I understand this permanently clears the query log",
        key="confirm_clear_query_log",
    )
    if st.button("🧹 Clear query log", disabled=not confirm_clear):
        try:
            _delete("/runbook-queries")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Clear failed: {exc}")
        else:
            st.success("Query log cleared.")
            st.cache_data.clear()
            st.rerun()


def _render_health_tab(stats: dict) -> None:
    st.subheader("Agent health")

    col1, col2 = st.columns(2)
    with col1:
        try:
            health = _get_json("/healthz")
            st.success(f"**/healthz** — {health.get('status')} (version {health.get('version')})")
        except Exception as exc:  # noqa: BLE001
            st.error(f"/healthz unreachable: {exc}")
    with col2:
        try:
            ready = _get_json("/readyz")
            ok = ready.get("status") == "ready"
            (st.success if ok else st.warning)(f"**/readyz** — {ready.get('status')}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"/readyz unreachable: {exc}")

    st.markdown("#### Raw `/graph/stats`")
    st.json(stats)


if __name__ == "__main__":
    main()
