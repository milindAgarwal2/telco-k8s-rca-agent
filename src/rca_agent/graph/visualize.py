"""Interactive graph visualization (pyvis -> vis.js HTML).

Renders a :class:`DependencyGraph` (or a neighborhood subgraph) to a standalone
interactive HTML page: drag/zoom/hover, nodes colored by health and shaped by
kind, edges labeled by relationship. Lives in the ``[viz]`` extra, imported
lazily so the core service does not require it.
"""
from __future__ import annotations

from rca_agent.graph.dependency_graph import DependencyGraph, Health, NodeKind

# Node shape by kind (vis.js shapes).
_SHAPE = {
    NodeKind.nf.value: "hexagon",
    NodeKind.service.value: "diamond",
    NodeKind.pod.value: "dot",
    NodeKind.node.value: "square",
    NodeKind.deployment.value: "triangle",
    NodeKind.replicaset.value: "triangleDown",
    NodeKind.configmap.value: "box",
    NodeKind.secret.value: "box",
    NodeKind.pvc.value: "database",
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
    return "<br>".join(lines)


def render_graph_html(graph: DependencyGraph, title: str = "RCA dependency graph",
                      height: str = "750px", hide_orphans: bool = True,
                      with_pod_filter: bool = True) -> str:
    """Return a standalone interactive HTML document for the whole graph.

    ``hide_orphans`` (default True) drops edgeless nodes (typically unmounted
    secrets/configmaps) that just clutter the view.
    ``with_pod_filter`` (default True) injects a pod picker that reloads the
    page scoped to the selected pod's neighborhood.
    """
    return _render(graph, list(graph.graph.nodes), title, height, hide_orphans,
                   selected_pod=None, with_pod_filter=with_pod_filter)


def render_neighborhood_html(graph: DependencyGraph, node_id: str, radius: int = 2,
                             height: str = "750px", hide_orphans: bool = False,
                             with_pod_filter: bool = True) -> str:
    """Return interactive HTML for the neighborhood around ``node_id``.

    Orphans are kept here by default — in a neighborhood you usually *want* to
    see the mounted configmaps/secrets of the focal pod.
    """
    nb = graph.neighborhood(node_id, radius=radius)
    ids = [n["id"] for n in nb["nodes"]]
    return _render(graph, ids, f"Neighborhood of {node_id} (r={radius})", height,
                   hide_orphans, selected_pod=node_id, radius=radius,
                   with_pod_filter=with_pod_filter)


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
            radius: int = 2, with_pod_filter: bool = False) -> str:
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

    net = Network(height=height, width="100%", directed=True,
                  bgcolor="#ffffff", font_color="#222222", heading=title)

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

    # Inject the pod picker (if requested) right after <body> so it overlays
    # the graph canvas as a fixed control.
    if with_pod_filter:
        filter_html = _pod_filter_html(graph, selected_pod, radius)
        if "<body>" in html:
            html = html.replace("<body>", "<body>" + filter_html, 1)
        else:
            html = filter_html + html
    return html
