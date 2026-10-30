"""Interactive graph visualization (pyvis -> vis.js HTML).

Renders a :class:`DependencyGraph` (or a neighborhood subgraph) to a standalone
interactive HTML page: drag/zoom/hover, nodes colored by health and shaped by
kind, edges labeled by relationship. Lives in the ``[viz]`` extra, imported
lazily so the core service does not require it.
"""
from __future__ import annotations

import re

from rca_agent.graph.dependency_graph import DependencyGraph, Health, NodeKind

# pyvis's template unconditionally emits <center><h1>{{heading}}</h1></center>
# TWICE regardless of whether `heading` is empty -- passing heading="" just
# leaves two empty shells (<h1></h1>) rather than skipping the block. Strip
# them entirely rather than leaving dead markup around.
_EMPTY_HEADING_RE = re.compile(r"<center>\s*<h1>\s*</h1>\s*</center>\s*")

# Node shape by kind (vis.js shapes) -- every kind is a DISTINCT shape so the
# shape alone identifies the kind (color is reserved for health, see below).
_SHAPE = {
    NodeKind.nf.value: "star",
    NodeKind.service.value: "diamond",
    NodeKind.pod.value: "dot",
    NodeKind.node.value: "square",
    NodeKind.deployment.value: "triangle",
    NodeKind.replicaset.value: "triangleDown",
    NodeKind.configmap.value: "box",
    NodeKind.secret.value: "database",
    NodeKind.pvc.value: "hexagon",
}

# Human labels for the legend.
_KIND_LABEL = {
    NodeKind.nf.value: "network function",
    NodeKind.service.value: "service",
    NodeKind.pod.value: "pod",
    NodeKind.node.value: "worker node",
    NodeKind.deployment.value: "deployment",
    NodeKind.replicaset.value: "replicaset",
    NodeKind.configmap.value: "configmap",
    NodeKind.secret.value: "secret",
    NodeKind.pvc.value: "pvc",
}

# Unicode glyphs approximating the vis.js shapes, for the HTML legend.
_SHAPE_GLYPH = {
    "star": "★", "diamond": "◆", "dot": "●", "square": "■",
    "triangle": "▲", "triangleDown": "▼", "box": "▭", "database": "🛢",
    "hexagon": "⬢",
}

# Node color by rolled-up health (falls back to the boolean 'healthy' attr).
_HEALTH_COLOR = {
    Health.healthy.value: "#4caf50",   # green
    Health.degraded.value: "#ff9800",  # orange
    Health.down.value: "#e53935",      # red
    Health.unknown.value: "#9e9e9e",   # grey
}

# Edge color by relationship.
_EDGE_COLOR = {
    "calls": "#1e88e5",
    "runs_on": "#8e24aa",
    "mounts": "#00897b",
    "managed_by": "#6d4c41",
    "selects": "#c0ca33",
}


def _node_color(attrs: dict) -> str:
    health = attrs.get("health")
    if health in _HEALTH_COLOR:
        return _HEALTH_COLOR[health]
    # Fall back to the boolean flag for nodes that only set `healthy`.
    if attrs.get("healthy") is False:
        return _HEALTH_COLOR[Health.down.value]
    if attrs.get("healthy") is True:
        return _HEALTH_COLOR[Health.healthy.value]
    return _HEALTH_COLOR[Health.unknown.value]


def _node_title(node_id: str, attrs: dict) -> str:
    """Hover tooltip (HTML)."""
    lines = [f"<b>{attrs.get('display', node_id)}</b>", f"kind: {attrs.get('kind')}"]
    for key in ("health", "health_reason", "phase", "replicas"):
        if attrs.get(key) not in (None, ""):
            lines.append(f"{key}: {attrs[key]}")
    # Age + restarts (pods) — the Task-3 detail, also surfaced on click.
    age = _format_age(attrs.get("pod_created_at"))
    if age:
        lines.append(f"age: {age}")
    if attrs.get("restart_count") not in (None, ""):
        lines.append(f"restarts: {attrs['restart_count']}")
    return "<br>".join(lines)


def _format_age(created_at) -> str | None:
    """Human age like '3d 4h' / '12m' from an ISO creation timestamp. None-safe."""
    if not created_at:
        return None
    from datetime import datetime, timezone
    try:
        s = str(created_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 0:
        return "just now"
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def render_graph_html(graph: DependencyGraph, title: str = "RCA dependency graph",
                      height: str = "750px", hide_orphans: bool = True,
                      with_pod_filter: bool = True,
                      incident_index: dict | None = None) -> str:
    """Return a standalone interactive HTML document for the whole graph.

    ``hide_orphans`` (default True) drops edgeless nodes (typically unmounted
    secrets/configmaps) that just clutter the view.
    ``with_pod_filter`` (default True) injects a pod picker that reloads the
    page scoped to the selected pod's neighborhood.
    ``incident_index`` maps node_id -> incident_id so clicking an unhealthy pod
    can open its incident (Task 2).
    """
    return _render(graph, list(graph.graph.nodes), title, height, hide_orphans,
                   selected_pod=None, with_pod_filter=with_pod_filter,
                   incident_index=incident_index)


def render_neighborhood_html(graph: DependencyGraph, node_id: str, radius: int = 2,
                             height: str = "750px", hide_orphans: bool = False,
                             with_pod_filter: bool = True,
                             incident_index: dict | None = None) -> str:
    """Return interactive HTML for the neighborhood around ``node_id``.

    Orphans are kept here by default — in a neighborhood you usually *want* to
    see the mounted configmaps/secrets of the focal pod.
    """
    nb = graph.neighborhood(node_id, radius=radius)
    ids = [n["id"] for n in nb["nodes"]]
    return _render(graph, ids, f"Neighborhood of {node_id} (r={radius})", height,
                   hide_orphans, selected_pod=node_id, radius=radius,
                   with_pod_filter=with_pod_filter, incident_index=incident_index)


# Dot color used in the dropdown labels, mirroring node health colors.
_HEALTH_DOT = {
    Health.healthy.value: "🟢",
    Health.degraded.value: "🟠",
    Health.down.value: "🔴",
    Health.unknown.value: "⚪",
}


def _pod_filter_html(graph: DependencyGraph, selected_pod: str | None,
                     radius: int) -> str:
    """A fixed-position pod picker overlaid on the graph page.

    Changing the selection navigates to ``/graph/view/<pod>?radius=N`` so the
    page reloads scoped to that pod's neighborhood. The first option
    ("— show full graph —") navigates back to ``/graph/view``.
    """
    options = ['<option value="">— show full graph —</option>']
    for p in graph.pods():
        dot = _HEALTH_DOT.get(p.get("health"), "")
        label = f"{dot} {p['display']}".strip()
        sel = " selected" if p["id"] == selected_pod else ""
        # Escape quotes in ids/labels defensively.
        pid = str(p["id"]).replace('"', "&quot;")
        label = label.replace("<", "&lt;").replace(">", "&gt;")
        options.append(f'<option value="{pid}"{sel}>{label}</option>')
    options_html = "\n".join(options)

    return f"""
    <div id="pod-filter" style="position:fixed;top:10px;left:10px;z-index:1000;
         background:rgba(255,255,255,0.95);border:1px solid #ccc;border-radius:6px;
         padding:8px 10px;font-family:sans-serif;font-size:13px;
         box-shadow:0 1px 4px rgba(0,0,0,0.2);">
      <label for="pod-select" style="font-weight:bold;margin-right:6px;">Pod:</label>
      <select id="pod-select" style="padding:3px 6px;max-width:320px;">
        {options_html}
      </select>
      <span style="margin-left:8px;color:#666;">radius</span>
      <select id="pod-radius" style="padding:3px 4px;">
        <option value="1"{" selected" if radius == 1 else ""}>1</option>
        <option value="2"{" selected" if radius == 2 else ""}>2</option>
        <option value="3"{" selected" if radius == 3 else ""}>3</option>
      </select>
    </div>
    <script type="text/javascript">
      (function () {{
        var sel = document.getElementById('pod-select');
        var rad = document.getElementById('pod-radius');
        function go() {{
          var pod = sel.value;
          if (!pod) {{ window.location.href = '/graph/view'; return; }}
          var r = rad ? rad.value : '2';
          window.location.href = '/graph/view/' + encodeURIComponent(pod)
                                 + '?radius=' + encodeURIComponent(r);
        }}
        sel.addEventListener('change', go);
        if (rad) rad.addEventListener('change', function () {{
          if (sel.value) go();
        }});
      }})();
    </script>
    """


def _render(graph: DependencyGraph, node_ids, title: str, height: str,
            hide_orphans: bool = False, selected_pod: str | None = None,
            radius: int = 2, with_pod_filter: bool = False,
            incident_index: dict | None = None) -> str:
    try:
        from pyvis.network import Network  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "pyvis is not installed. Install the viz extra: pip install '.[viz]'"
        ) from exc

    g = graph.graph
    wanted = set(node_ids)

    # Which edges are within the selected set.
    edges = [(u, v, k) for u, v, k in g.edges(keys=True)
             if u in wanted and v in wanted]

    # Optionally drop orphan nodes (no edge within the view) — these are usually
    # unmounted secrets/configmaps that just clutter the picture.
    if hide_orphans:
        connected = set()
        for u, v, _ in edges:
            connected.add(u)
            connected.add(v)
        node_ids = [n for n in node_ids if n in connected]
        wanted = set(node_ids)
        edges = [(u, v, k) for u, v, k in edges if u in wanted and v in wanted]

    # No `heading=title` here on purpose: pyvis's own template renders that
    # as a big centered <h1> TWICE (a template quirk, not a bug on our
    # side), eating most of the viewport. A small fixed-position corner
    # label (_title_label_html, injected below) replaces it.
    net = Network(height=height, width="100%", directed=True,
                  bgcolor="#ffffff", font_color="#222222", heading="")

    for nid in node_ids:
        attrs = dict(g.nodes[nid])
        net.add_node(
            nid,
            label=str(attrs.get("display", nid)),
            color=_node_color(attrs),
            shape=_SHAPE.get(attrs.get("kind"), "dot"),
            title=_node_title(nid, attrs),
            borderWidth=2,
        )
    for u, v, k in edges:
        net.add_edge(u, v, label=k, color=_EDGE_COLOR.get(k, "#888888"),
                     arrows="to", font={"size": 10, "align": "middle"})

    # Run physics only to lay the graph out, then FREEZE it so nodes stop
    # drifting and the graph is readable. barnesHut with a stabilization cap;
    # physics is disabled once stabilized (stopped), and re-enabled only while
    # a node is being dragged.
    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "barnesHut": {"gravitationalConstant": -8000, "springLength": 160,
                      "springConstant": 0.04, "damping": 0.6},
        "stabilization": {"enabled": true, "iterations": 300,
                          "updateInterval": 25, "fit": true},
        "minVelocity": 0.75
      },
      "interaction": {"hover": true, "tooltipDelay": 100,
                      "dragNodes": true, "navigationButtons": true},
      "edges": {"smooth": false}
    }
    """)
    html = net.generate_html(notebook=False)
    html = _EMPTY_HEADING_RE.sub("", html)

    # Freeze physics once the initial stabilization finishes, so the layout
    # stops moving entirely. (vis.js emits 'stabilizationIterationsDone'.)
    freeze_js = """
    <script type="text/javascript">
      (function () {
        function wire() {
          if (typeof network === 'undefined') { return setTimeout(wire, 100); }
          network.on('stabilizationIterationsDone', function () {
            network.setOptions({physics: false});
          });
          // Safety net: hard stop after 4s even if the event is missed.
          setTimeout(function () { network.setOptions({physics: false}); }, 4000);
        }
        wire();
      })();
    </script>
    """
    # Inject right before </body> so `network` is already defined.
    if "</body>" in html:
        html = html.replace("</body>", freeze_js + "</body>")
    else:
        html += freeze_js

    # Small fixed-position corner label replacing pyvis's own bulky duplicated
    # <h1> heading (see the Network(heading="") comment above) -- top-right,
    # away from the pod picker (top-left).
    label_html = _title_label_html(title)
    if "<body>" in html:
        html = html.replace("<body>", "<body>" + label_html, 1)
    else:
        html = label_html + html

    # Legend (shape=kind, color=health) — bottom-left, out of the way of the
    # title label (top-right) and pod picker (top-left).
    legend_html = _legend_html()
    if "<body>" in html:
        html = html.replace("<body>", "<body>" + legend_html, 1)
    else:
        html = legend_html + html

    # Inject the pod picker (if requested) right after <body> so it overlays
    # the graph canvas as a fixed control.
    if with_pod_filter:
        filter_html = _pod_filter_html(graph, selected_pod, radius)
        if "<body>" in html:
            html = html.replace("<body>", "<body>" + filter_html, 1)
        else:
            html = filter_html + html

    # Click handler + info panel (Tasks 2 & 3): clicking a node shows its age +
    # restart count (and health); clicking an UNHEALTHY pod that has an incident
    # navigates the parent dashboard to that incident on the Incidents tab.
    click_html = _click_handler_html(graph, node_ids, incident_index or {})
    if "</body>" in html:
        html = html.replace("</body>", click_html + "</body>")
    else:
        html += click_html
    return html


def _click_handler_html(graph: DependencyGraph, node_ids, incident_index: dict) -> str:
    """A node-info panel + vis.js click handler.

    On click: fill a fixed panel with the node's kind/health/age/restarts. If
    the node is an unhealthy pod with a known incident, also offer (and
    auto-trigger) navigation to that incident on the parent dashboard's
    Incidents tab via ``window.parent`` (the graph is embedded in an iframe).
    """
    import json as _json

    info: dict[str, dict] = {}
    g = graph.graph
    for nid in node_ids:
        a = dict(g.nodes.get(nid, {}))
        info[str(nid)] = {
            "display": str(a.get("display", nid)),
            "kind": a.get("kind"),
            "health": a.get("health"),
            "reason": a.get("health_reason"),
            "age": _format_age(a.get("pod_created_at")),
            "restarts": a.get("restart_count"),
            "incident": incident_index.get(nid),
            "unhealthy": a.get("healthy") is False or a.get("health") == "down",
        }
    info_js = _json.dumps(info)

    return """
    <div id="node-info" style="position:fixed;bottom:10px;right:10px;z-index:1000;
         display:none;background:rgba(255,255,255,0.97);border:1px solid #ccc;
         border-radius:6px;padding:10px 12px;font-family:sans-serif;font-size:12px;
         color:#222;box-shadow:0 1px 4px rgba(0,0,0,0.25);max-width:320px;"></div>
    <script type="text/javascript">
      (function () {
        var INFO = __NODE_INFO__;
        function esc(s){return String(s==null?'':s).replace(/[&<>]/g,function(c){
          return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
        function wire() {
          if (typeof network === 'undefined') { return setTimeout(wire, 100); }
          var panel = document.getElementById('node-info');
          network.on('click', function (params) {
            if (!params.nodes || !params.nodes.length) { panel.style.display='none'; return; }
            var id = params.nodes[0];
            var d = INFO[id]; if (!d) { panel.style.display='none'; return; }
            var html = '<b>' + esc(d.display) + '</b><br>kind: ' + esc(d.kind);
            if (d.health) html += '<br>health: ' + esc(d.health);
            if (d.reason) html += '<br>reason: ' + esc(d.reason);
            if (d.age != null) html += '<br>age: ' + esc(d.age);
            if (d.restarts != null) html += '<br>restarts: ' + esc(d.restarts);
            if (d.incident) {
              var url = '/ui/incidents/' + encodeURIComponent(d.incident);
              html += '<br><a href="#" id="go-incident">\u2192 open incident ' +
                      esc(d.incident) + '</a>';
            }
            panel.innerHTML = html;
            panel.style.display = 'block';
            // Unhealthy pod with an incident -> navigate the PARENT dashboard to
            // the Incidents tab and open this incident (graph is in an iframe).
            if (d.incident && d.unhealthy) {
              openIncident(d.incident);
            }
            var a = document.getElementById('go-incident');
            if (a) a.addEventListener('click', function(e){e.preventDefault();
              openIncident(d.incident);});
          });
        }
        function openIncident(incidentId) {
          try {
            if (window.parent && window.parent !== window &&
                typeof window.parent.openIncidentFromGraph === 'function') {
              window.parent.openIncidentFromGraph(incidentId);
              return;
            }
          } catch (e) { /* cross-origin / not embedded */ }
          // Fallback: open the incident detail directly.
          window.open('/ui/incidents/' + encodeURIComponent(incidentId), '_blank');
        }
        wire();
      })();
    </script>
    """.replace("__NODE_INFO__", info_js)


def _title_label_html(title: str) -> str:
    """A small, unobtrusive corner label naming what's shown -- replaces
    pyvis's own ``heading`` output, which renders as a large centered <h1>
    (twice, per its template) and eats most of the viewport."""
    safe = title.replace("<", "&lt;").replace(">", "&gt;")
    return f"""
    <div style="position:fixed;top:10px;right:10px;z-index:999;
         background:rgba(255,255,255,0.9);border:1px solid #ddd;border-radius:4px;
         padding:4px 8px;font-family:sans-serif;font-size:12px;color:#555;
         max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
         title="{safe}">
      {safe}
    </div>
    """


def _legend_html() -> str:
    """Fixed-position legend: shape = node kind, color = health. Built from the
    same ``_SHAPE``/``_HEALTH_COLOR`` maps the renderer uses, so it can't drift
    from what's actually drawn."""
    kind_rows = "".join(
        f'<div style="white-space:nowrap;">'
        f'<span style="display:inline-block;width:18px;text-align:center;">'
        f'{_SHAPE_GLYPH.get(_SHAPE.get(k, "dot"), "●")}</span> {label}</div>'
        for k, label in _KIND_LABEL.items()
    )
    health_rows = "".join(
        f'<div style="white-space:nowrap;">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
        f'background:{color};margin-right:6px;vertical-align:middle;"></span>{state}</div>'
        for state, color in [
            (Health.healthy.value, _HEALTH_COLOR[Health.healthy.value]),
            (Health.degraded.value, _HEALTH_COLOR[Health.degraded.value]),
            (Health.down.value, _HEALTH_COLOR[Health.down.value]),
            (Health.unknown.value, _HEALTH_COLOR[Health.unknown.value]),
        ]
    )
    return f"""
    <div id="graph-legend" style="position:fixed;bottom:10px;left:10px;z-index:999;
         background:rgba(255,255,255,0.95);border:1px solid #ccc;border-radius:6px;
         padding:8px 12px;font-family:sans-serif;font-size:12px;color:#333;
         box-shadow:0 1px 4px rgba(0,0,0,0.2);line-height:1.5;">
      <div style="display:flex;gap:18px;">
        <div>
          <div style="font-weight:bold;margin-bottom:3px;">Shape = kind</div>
          {kind_rows}
        </div>
        <div>
          <div style="font-weight:bold;margin-bottom:3px;">Color = health</div>
          {health_rows}
        </div>
      </div>
    </div>
    """
