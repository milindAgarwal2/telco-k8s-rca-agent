"""Live dependency graph of the 5G core, backed by NetworkX.

Nodes model network functions/services, pods, nodes, ConfigMaps/Secrets, PVCs
and deployments (plus revisions). Edges model relationships: ``calls``,
``runs_on``, ``mounts``, ``managed_by``.

Every node and edge carries timestamps (``changed_at`` history) so the agent can
reconstruct what the graph looked like when a fault started. The graph is a
directed multigraph: ``A --calls--> B`` means A depends on B (B is *upstream* of
A, and a candidate cause of A's failure).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import networkx as nx


class NodeKind(str, Enum):
    nf = "network_function"
    service = "service"
    pod = "pod"
    node = "node"
    configmap = "configmap"
    secret = "secret"
    pvc = "pvc"
    deployment = "deployment"
    replicaset = "replicaset"


class EdgeKind(str, Enum):
    calls = "calls"          # A depends on B (B upstream of A)
    runs_on = "runs_on"      # pod runs_on node
    mounts = "mounts"        # pod mounts configmap/secret/pvc
    managed_by = "managed_by"  # pod managed_by replicaset/deployment/statefulset
    selects = "selects"      # service selects pod


class Health(str, Enum):
    """Rolled-up health state of a node.

    For a workload (NF) node this is derived from its pods:
      healthy  — all pods ready
      degraded — some pods ready, some not (partial outage, replicas absorbing)
      down     — no pods ready
      unknown  — no pods / no information
    """

    healthy = "healthy"
    degraded = "degraded"
    down = "down"
    unknown = "unknown"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChangeRecord:
    """A timestamped change to the graph (node or edge add/update/remove)."""

    at: datetime
    op: str              # "add" | "update" | "remove"
    element: str         # "node" | "edge"
    ref: str             # node id or "src->dst:kind"
    detail: dict = field(default_factory=dict)


class DependencyGraph:
    """A timestamped directed dependency graph."""

    def __init__(self) -> None:
        self._g = nx.MultiDiGraph()
        self.changes: list[ChangeRecord] = []
        self.last_rebuilt: datetime | None = None

    # ----- mutation (populated by builders, never by the LLM) -----
    def upsert_node(self, node_id: str, kind: NodeKind, **attrs) -> None:
        now = _now()
        exists = self._g.has_node(node_id)
        if not exists:
            self._g.add_node(node_id, kind=kind.value, created_at=now, **attrs)
            self._record("add", "node", node_id, {"kind": kind.value, **attrs})
        else:
            self._g.nodes[node_id].update(attrs)
            # ``add_edge`` to a not-yet-created target implicitly creates that
            # node with NO attributes at all (networkx behavior). If an edge
            # to this id was added before anything upserted it, ``exists`` is
            # already True by the time its real upsert_node call arrives, but
            # with no ``kind`` yet — ``setdefault`` backfills it without
            # clobbering a kind a prior, correct upsert already set.
            self._g.nodes[node_id].setdefault("kind", kind.value)
            self._g.nodes[node_id]["changed_at"] = now
            self._record("update", "node", node_id, attrs)

    def upsert_edge(self, src: str, dst: str, kind: EdgeKind, **attrs) -> None:
        now = _now()
        ref = f"{src}->{dst}:{kind.value}"
        exists = self._g.has_edge(src, dst, key=kind.value)
        self._g.add_edge(src, dst, key=kind.value, kind=kind.value,
                         changed_at=now, **attrs)
        self._record("update" if exists else "add", "edge", ref, attrs)

    def remove_node(self, node_id: str) -> None:
        if self._g.has_node(node_id):
            self._g.remove_node(node_id)
            self._record("remove", "node", node_id, {})

    def set_health(self, node_id: str, healthy: bool, reason: str = "") -> None:
        if self._g.has_node(node_id):
            self.upsert_node(
                node_id,
                NodeKind(self._g.nodes[node_id]["kind"]),
                healthy=healthy,
                health_reason=reason,
                health=(Health.healthy if healthy else Health.down).value,
            )

    def set_health_state(self, node_id: str, state: Health, reason: str = "") -> None:
        """Set the rolled-up health state (healthy/degraded/down/unknown)."""
        if self._g.has_node(node_id):
            self.upsert_node(
                node_id,
                NodeKind(self._g.nodes[node_id]["kind"]),
                healthy=(state == Health.healthy),
                health=state.value,
                health_reason=reason,
            )

    def roll_up_health(self, nf_id: str) -> Health:
        """Derive and store an NF node's health from its managed pods.

        Looks at pods reachable via ``managed_by`` edges pointing at ``nf_id``
        (pod --managed_by--> nf). ``healthy`` attr on each pod drives the rollup:
        all healthy -> healthy, none healthy -> down, mixed -> degraded, no pods
        -> unknown.
        """
        state, reason = self._rollup_from_pods(self.managed_pods(nf_id))
        self.set_health_state(nf_id, state, reason)
        return state

    def roll_up_service_health(self, service_id: str) -> Health:
        """Derive and store a Service node's health from the pods it ``selects``.

        Mirrors :meth:`roll_up_health`, but walks ``selects`` out-edges
        (service --selects--> pod) instead of ``managed_by`` in-edges. This is
        what makes a ``calls`` edge TO a service a meaningful upstream-health
        signal — without it, a service node defaults to "healthy" regardless
        of the state of the pods behind it.
        """
        state, reason = self._rollup_from_pods(self.selected_pods(service_id))
        self.set_health_state(service_id, state, reason)
        return state

    def _rollup_from_pods(self, pods: list[str]) -> tuple[Health, str]:
        if not pods:
            return Health.unknown, "no pods found"
        ready = [p for p in pods if self.is_healthy(p)]
        if len(ready) == len(pods):
            return Health.healthy, f"{len(ready)}/{len(pods)} pods ready"
        if not ready:
            return Health.down, f"0/{len(pods)} pods ready"
        return Health.degraded, f"{len(ready)}/{len(pods)} pods ready"

    def managed_pods(self, nf_id: str) -> list[str]:
        """Pods that are ``managed_by`` the given workload node (direct or via RS)."""
        pods: list[str] = []
        for u, _v, k in self._g.in_edges(nf_id, keys=True):
            if k != EdgeKind.managed_by.value:
                continue
            if self._g.nodes.get(u, {}).get("kind") == NodeKind.pod.value:
                pods.append(u)
            else:
                # one more hop: pod -> replicaset -> deployment
                for uu, _vv, kk in self._g.in_edges(u, keys=True):
                    if kk == EdgeKind.managed_by.value and \
                            self._g.nodes.get(uu, {}).get("kind") == NodeKind.pod.value:
                        pods.append(uu)
        return pods

    def selected_pods(self, service_id: str) -> list[str]:
        """Pods a Service ``selects`` (direct ``selects`` out-edges)."""
        pods: list[str] = []
        for _u, v, k in self._g.out_edges(service_id, keys=True):
            if k == EdgeKind.selects.value and \
                    self._g.nodes.get(v, {}).get("kind") == NodeKind.pod.value:
                pods.append(v)
        return pods

    def _record(self, op: str, element: str, ref: str, detail: dict) -> None:
        self.changes.append(ChangeRecord(at=_now(), op=op, element=element,
                                         ref=ref, detail=detail))

    # ----- queries (read-only) -----
    @property
    def graph(self) -> nx.MultiDiGraph:
        return self._g

    def node(self, node_id: str) -> dict | None:
        return dict(self._g.nodes[node_id]) if self._g.has_node(node_id) else None

    def pods(self) -> list[dict]:
        """All pod nodes, sorted by display name — for the viz dropdown.

        Returns ``[{id, display, health, component}]`` so the UI can list and
        group pods without re-walking the whole graph.
        """
        out = []
        for nid, attrs in self._g.nodes(data=True):
            if attrs.get("kind") == NodeKind.pod.value:
                out.append({
                    "id": nid,
                    "display": attrs.get("display", nid),
                    "health": attrs.get("health", "unknown"),
                    "component": attrs.get("component"),
                })
        out.sort(key=lambda p: str(p["display"]).lower())
        return out

    def is_healthy(self, node_id: str) -> bool:
        return bool(self._g.nodes.get(node_id, {}).get("healthy", True))

    def upstream(self, node_id: str, max_depth: int = 3) -> list[str]:
        """Services that ``node_id`` depends on (candidate causes).

        Follows ``calls`` edges outward: ``node_id --calls--> dependency``.
        """
        return self._traverse(node_id, EdgeKind.calls, reverse=False, max_depth=max_depth)

    def downstream(self, node_id: str, max_depth: int = 3) -> list[str]:
        """Services that depend on ``node_id`` (blast radius).

        Follows ``calls`` edges inward: ``dependent --calls--> node_id``.
        """
        return self._traverse(node_id, EdgeKind.calls, reverse=True, max_depth=max_depth)

    def unhealthy_upstream(self, node_id: str, max_depth: int = 3) -> list[str]:
        """Upstream dependencies currently marked unhealthy — candidate causes."""
        return [n for n in self.upstream(node_id, max_depth) if not self.is_healthy(n)]

    def calls_edge_evidence(self, src: str, dst: str) -> str | None:
        """The citable ``evidence`` attribute on a direct ``calls`` edge
        ``src -> dst`` (e.g. ``"env:VAULT_ADDR"`` or
        ``"configmap:app-config.db_host"``), or ``None`` if there's no such
        edge or it carries no evidence (synthetic/test edges). Lets
        ``graph_walk`` cite exactly which env var or ConfigMap key produced
        the dependency, instead of just asserting one exists.
        """
        if not self._g.has_edge(src, dst, key=EdgeKind.calls.value):
            return None
        return self._g.get_edge_data(src, dst, key=EdgeKind.calls.value).get("evidence")

    def mounted_config(self, pod_id: str) -> set[str]:
        """Display names of configmaps/secrets the given pod mounts.

        Follows ``mounts`` edges from the pod to configmap/secret nodes and
        returns their human display names (the bare object name, not the
        prefixed graph id). Used to scope change-correlation: a config change
        can only be a cause for a pod that actually consumes that config.
        """
        out: set[str] = set()
        if not self._g.has_node(pod_id):
            return out
        for _u, v, k in self._g.out_edges(pod_id, keys=True):
            if k != EdgeKind.mounts.value:
                continue
            attrs = self._g.nodes.get(v, {})
            if attrs.get("kind") in (NodeKind.configmap.value, NodeKind.secret.value):
                out.add(attrs.get("display", v))
        return out

    def _traverse(self, start: str, kind: EdgeKind, reverse: bool,
                  max_depth: int) -> list[str]:
        if not self._g.has_node(start):
            return []
        seen: list[str] = []
        visited = {start}
        frontier = [start]
        depth = 0
        while frontier and depth < max_depth:
            nxt: list[str] = []
            for cur in frontier:
                edges = (self._g.in_edges(cur, keys=True) if reverse
                         else self._g.out_edges(cur, keys=True))
                for u, v, k in edges:
                    if k != kind.value:
                        continue
                    neighbor = u if reverse else v
                    if neighbor not in visited:
                        visited.add(neighbor)
                        seen.append(neighbor)
                        nxt.append(neighbor)
            frontier = nxt
            depth += 1
        return seen

    def changes_between(self, start: datetime, end: datetime) -> list[ChangeRecord]:
        """Graph changes within a time window — the change-correlation input."""
        return [c for c in self.changes if start <= c.at <= end]

    def neighborhood(self, node_id: str, radius: int = 1) -> dict:
        """A small subgraph summary for the Impact Explorer UI."""
        if not self._g.has_node(node_id):
            return {"nodes": [], "edges": []}
        nodes = {node_id}
        frontier = {node_id}
        for _ in range(radius):
            nxt: set[str] = set()
            for n in frontier:
                nxt.update(self._g.successors(n))
                nxt.update(self._g.predecessors(n))
            new = nxt - nodes
            nodes.update(new)
            frontier = new
            if not frontier:
                break
        sub = self._g.subgraph(nodes)
        return {
            "nodes": [
                {"id": n, **self._g.nodes[n]} for n in sub.nodes
            ],
            "edges": [
                {"src": u, "dst": v, "kind": k} for u, v, k in sub.edges(keys=True)
            ],
        }

    def stats(self) -> dict:
        return {
            "nodes": self._g.number_of_nodes(),
            "edges": self._g.number_of_edges(),
            "changes": len(self.changes),
            "last_rebuilt": self.last_rebuilt.isoformat() if self.last_rebuilt else None,
        }


def build_demo_graph() -> DependencyGraph:
    """A pod-centric demo graph for ONE application (no cluster needed).

    This mirrors exactly what ``GraphBuilder._rebuild_from_cluster`` produces, so
    the no-cluster view matches the real-cluster view: a workload (Deployment)
    manages a ReplicaSet which manages pods; pods run_on nodes, mount
    configmaps/secrets/pvcs, and a Service selects them. NF-to-NF ``calls`` edges
    are intentionally absent — we monitor a single app, not inter-NF topology.

    Scenario (the headline example): the UPF app has 3 pods; one was OOMKilled,
    so the workload rolls up to ``degraded``.
    """
    g = DependencyGraph()

    # Nodes (workers).
    g.upsert_node("worker-1", NodeKind.node, healthy=True, health=Health.healthy.value)
    g.upsert_node("worker-2", NodeKind.node, healthy=True, health=Health.healthy.value)

    # Config objects (prefixed ids, matching the real builder).
    g.upsert_node("configmap/upf-config", NodeKind.configmap, display="upf-config")
    g.upsert_node("secret/upf-secret", NodeKind.secret, display="upf-secret")
    g.upsert_node("pvc/upf-data", NodeKind.pvc, display="upf-data")

    # Workload -> ReplicaSet (managed_by).
    g.upsert_node("upf", NodeKind.deployment, replicas=3)
    g.upsert_node("upf-7c9", NodeKind.replicaset)
    g.upsert_edge("upf-7c9", "upf", EdgeKind.managed_by)

    # Service.
    g.upsert_node("service/upf", NodeKind.service, display="upf")

    # Pods: 3 replicas, one OOMKilled.
    pods = [
        ("upf-0", "worker-1", True, "ready"),
        ("upf-1", "worker-2", False, "OOMKilled"),
        ("upf-2", "worker-1", True, "ready"),
    ]
    for name, node, healthy, reason in pods:
        g.upsert_node(name, NodeKind.pod, healthy=healthy,
                      health=(Health.healthy if healthy else Health.down).value,
                      health_reason=reason, phase="Running")
        g.upsert_edge(name, node, EdgeKind.runs_on)
        g.upsert_edge(name, "upf-7c9", EdgeKind.managed_by)
        g.upsert_edge(name, "configmap/upf-config", EdgeKind.mounts)
        g.upsert_edge(name, "secret/upf-secret", EdgeKind.mounts)
        g.upsert_edge(name, "pvc/upf-data", EdgeKind.mounts)
        g.upsert_edge("service/upf", name, EdgeKind.selects)

    # Roll pod health up to the workload (2/3 ready -> degraded).
    g.roll_up_health("upf-7c9")
    g.roll_up_health("upf")

    g.last_rebuilt = _now()
    return g
