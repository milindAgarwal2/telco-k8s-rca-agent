"""Build the dependency graph from a running cluster (read-only).

Scope: a single NF/application in one namespace. The ``nf_selector`` label
selector narrows which objects belong to the app; an empty selector means the
whole namespace is treated as the one application.

Everything here is derived from native Kubernetes objects via get/list calls —
no traces, no static call map. The graph is the internal structure of the app:

    workload (Deployment/StatefulSet/DaemonSet)  [NF node, health rolled up]
      ^ managed_by   ReplicaSet ^ managed_by   pods
      pods --runs_on--> nodes
      pods --mounts--> configmaps / secrets / pvcs
      Service --selects--> pods

When ``cluster_enabled`` is False (default) we return the demo graph so the rest
of the system runs with no cluster.
"""
from __future__ import annotations

import logging

from rca_agent.config import Settings, get_settings
from rca_agent.graph.dependency_graph import (
    DependencyGraph,
    EdgeKind,
    Health,
    NodeKind,
    build_demo_graph,
)

logger = logging.getLogger("rca_agent.graph")


class GraphBuilder:
    """Builds and refreshes the dependency graph from cluster state."""

    def __init__(self, settings: Settings | None = None, kube_client=None) -> None:
        """``kube_client`` may be injected (a KubeClient or any object exposing
        ``core`` and ``apps`` read-only APIs) — used by tests with a fake client.
        When None and cluster is enabled, a real read-only client is built.
        """
        self.settings = settings or get_settings()
        self._graph = DependencyGraph()
        self._kube = kube_client

    @property
    def graph(self) -> DependencyGraph:
        return self._graph

    def rebuild(self) -> DependencyGraph:
        """Rebuild the graph from the current cluster state (atomic result)."""
        if not self.settings.cluster_enabled:
            self._graph = build_demo_graph()
            return self._graph
        return self._rebuild_from_cluster()

    # ------------------------------------------------------------------
    def _client(self):
        if self._kube is None:
            from rca_agent.tools.kube_client import build_kube_client
            self._kube = build_kube_client(self.settings.kubeconfig_mode)
        return self._kube

    def _rebuild_from_cluster(self) -> DependencyGraph:
        """Discover the monitored app and build a fresh graph from it."""
        kube = self._client()
        ns = self.settings.namespace
        sel = self.settings.nf_selector or None  # None = all objects in ns
        g = DependencyGraph()

        self._add_nodes(g)                # cluster-scoped: nodes
        self._add_workloads(g, kube, ns, sel)
        self._add_config_objects(g, kube, ns, sel)
        self._add_pods(g, kube, ns, sel)  # pods + edges + pod health
        self._add_services(g, kube, ns, sel)
        self._roll_up_workload_health(g)

        from rca_agent.graph.dependency_graph import _now
        g.last_rebuilt = _now()
        self._graph = g
        logger.info("graph rebuilt from cluster ns=%s selector=%s: %s",
                    ns, sel, g.stats())
        return g

    # ------------------------------------------------------------------
    def _add_nodes(self, g: DependencyGraph) -> None:
        kube = self._kube
        for node in _safe_list(lambda **kw: kube.core.list_node(**kw), "nodes"):
            name = node.metadata.name
            ready = _node_ready(node)
            g.upsert_node(name, NodeKind.node,
                          healthy=ready,
                          health=(Health.healthy if ready else Health.down).value)

    def _add_workloads(self, g, kube, ns, sel) -> None:
        for dep in _safe_list(
            lambda **kw: kube.apps.list_namespaced_deployment(ns, label_selector=sel, **kw),
            "deployments",
        ):
            g.upsert_node(dep.metadata.name, NodeKind.deployment,
                          replicas=_spec_replicas(dep))
        for sts in _safe_list(
            lambda **kw: kube.apps.list_namespaced_stateful_set(ns, label_selector=sel, **kw),
            "statefulsets",
        ):
            g.upsert_node(sts.metadata.name, NodeKind.deployment,
                          workload_kind="StatefulSet", replicas=_spec_replicas(sts))
        for ds in _safe_list(
            lambda **kw: kube.apps.list_namespaced_daemon_set(ns, label_selector=sel, **kw),
            "daemonsets",
        ):
            g.upsert_node(ds.metadata.name, NodeKind.deployment, workload_kind="DaemonSet")
        for rs in _safe_list(
            lambda **kw: kube.apps.list_namespaced_replica_set(ns, label_selector=sel, **kw),
            "replicasets",
        ):
            if _spec_replicas(rs) == 0 and not _status_replicas(rs):
                continue  # skip old scaled-down ReplicaSets
            g.upsert_node(rs.metadata.name, NodeKind.replicaset)
            for owner in rs.metadata.owner_references or []:
                g.upsert_edge(rs.metadata.name, owner.name, EdgeKind.managed_by)

    def _add_config_objects(self, g, kube, ns, sel) -> None:
        for cm in _safe_list(
            lambda **kw: kube.core.list_namespaced_config_map(ns, label_selector=sel, **kw),
            "configmaps",
        ):
            g.upsert_node(_cm_id(cm.metadata.name), NodeKind.configmap,
                          display=cm.metadata.name)
        for sec in _safe_list(
            lambda **kw: kube.core.list_namespaced_secret(ns, label_selector=sel, **kw),
            "secrets",
        ):
            g.upsert_node(_secret_id(sec.metadata.name), NodeKind.secret,
                          display=sec.metadata.name)
        for pvc in _safe_list(
            lambda **kw: kube.core.list_namespaced_persistent_volume_claim(
                ns, label_selector=sel, **kw),
            "pvcs",
        ):
            g.upsert_node(_pvc_id(pvc.metadata.name), NodeKind.pvc,
                          display=pvc.metadata.name)

    def _add_pods(self, g, kube, ns, sel) -> None:
        for pod in _safe_list(
            lambda **kw: kube.core.list_namespaced_pod(ns, label_selector=sel, **kw),
            "pods",
        ):
            name = pod.metadata.name
            healthy, reason = _pod_health(pod)
            g.upsert_node(name, NodeKind.pod, healthy=healthy,
                          health=(Health.healthy if healthy else Health.down).value,
                          health_reason=reason,
                          phase=getattr(pod.status, "phase", None))

            # runs_on node
            node_name = getattr(pod.spec, "node_name", None)
            if node_name:
                g.upsert_node(node_name, NodeKind.node)  # ensure exists
                g.upsert_edge(name, node_name, EdgeKind.runs_on)

            # managed_by owner (ReplicaSet / StatefulSet / DaemonSet / Deployment)
            for owner in pod.metadata.owner_references or []:
                g.upsert_edge(name, owner.name, EdgeKind.managed_by)

            # mounts: volumes referencing configmaps / secrets / pvcs
            for vol in getattr(pod.spec, "volumes", None) or []:
                if getattr(vol, "config_map", None):
                    g.upsert_edge(name, _cm_id(vol.config_map.name), EdgeKind.mounts)
                if getattr(vol, "secret", None):
                    sname = getattr(vol.secret, "secret_name", None)
                    if sname:
                        g.upsert_edge(name, _secret_id(sname), EdgeKind.mounts)
                pvc = getattr(vol, "persistent_volume_claim", None)
                if pvc:
                    g.upsert_edge(name, _pvc_id(pvc.claim_name), EdgeKind.mounts)

            # mounts via envFrom (configMapRef / secretRef) on containers
            for container in getattr(pod.spec, "containers", None) or []:
                for env_from in getattr(container, "env_from", None) or []:
                    if getattr(env_from, "config_map_ref", None):
                        g.upsert_edge(name, _cm_id(env_from.config_map_ref.name),
                                      EdgeKind.mounts)
                    if getattr(env_from, "secret_ref", None):
                        g.upsert_edge(name, _secret_id(env_from.secret_ref.name),
                                      EdgeKind.mounts)

    def _add_services(self, g, kube, ns, sel) -> None:
        for svc in _safe_list(
            lambda **kw: kube.core.list_namespaced_service(ns, label_selector=sel, **kw),
            "services",
        ):
            sid = _svc_id(svc.metadata.name)
            g.upsert_node(sid, NodeKind.service, display=svc.metadata.name)
            selector = getattr(svc.spec, "selector", None) or {}
            if not selector:
                continue
            sel_str = _as_selector(selector)
            for pod in _safe_list(
                lambda s=sel_str, **kw: kube.core.list_namespaced_pod(ns, label_selector=s, **kw),
                "service pods",
            ):
                if g.node(pod.metadata.name):
                    g.upsert_edge(sid, pod.metadata.name, EdgeKind.selects)

    def _roll_up_workload_health(self, g: DependencyGraph) -> None:
        for node_id in list(g.graph.nodes):
            if g.graph.nodes[node_id].get("kind") in (
                NodeKind.deployment.value, NodeKind.replicaset.value
            ):
                g.roll_up_health(node_id)


# ---------------------------------------------------------------------------
# Helpers for reading the kube object model (works with real + fake objects).
# ---------------------------------------------------------------------------
def _items(list_result):
    return getattr(list_result, "items", None) or []


# Server-side pagination + per-request timeout keep a huge namespace from
# hanging or ballooning memory on a single unbounded list. The kubernetes
# client accepts ``limit``/``_continue`` for chunked lists and
# ``_request_timeout`` (connect, read) seconds per call.
_LIST_PAGE_SIZE = 500
_LIST_REQUEST_TIMEOUT = (5, 30)  # (connect, read) seconds


def _safe_list(call, label: str):
    """Call a kube ``list_*`` function, tolerating permission/API errors.

    On an OCP namespace a non-admin user is often forbidden from listing some
    resource types (e.g. cluster-scoped ``nodes`` or namespace ``secrets``).
    A single 403 must not blank out the whole graph — we log a warning and
    return an empty list so the rest of the build proceeds.

    The call is paginated server-side (``limit``/``_continue``) and bounded by a
    per-request timeout, so a large namespace completes promptly instead of
    hanging on one unbounded list. ``call`` must accept ``**kw`` so these
    options can be forwarded to the underlying kube ``list_*`` method; if it
    does not (e.g. a test stub), we fall back to a single plain call.
    """
    items: list = []
    cont: str | None = None
    try:
        while True:
            kw = {"limit": _LIST_PAGE_SIZE,
                  "_request_timeout": _LIST_REQUEST_TIMEOUT}
            if cont:
                kw["_continue"] = cont
            try:
                result = call(**kw)
            except TypeError:
                # The call doesn't accept pagination kwargs (test stub / simple
                # lambda) — fall back to one plain call.
                return _items(call())
            items.extend(_items(result))
            meta = getattr(result, "metadata", None)
            cont = getattr(meta, "_continue", None) or getattr(meta, "continue", None)
            if not cont:
                break
        return items
    except Exception as exc:  # noqa: BLE001 — tolerate ApiException/403/conn errors
        status = getattr(exc, "status", None)
        reason = getattr(exc, "reason", None) or type(exc).__name__
        logger.warning("skipping %s: cannot list (%s %s)", label, status, reason)
        return []


def _spec_replicas(obj) -> int:
    return getattr(getattr(obj, "spec", None), "replicas", 0) or 0


def _status_replicas(obj) -> int:
    return getattr(getattr(obj, "status", None), "replicas", 0) or 0


def _node_ready(node) -> bool:
    conds = getattr(getattr(node, "status", None), "conditions", None) or []
    for c in conds:
        if getattr(c, "type", None) == "Ready":
            return getattr(c, "status", "False") == "True"
    return True  # assume ready if no condition reported


def _pod_health(pod) -> tuple[bool, str]:
    """Return (healthy, reason) from pod phase + container statuses."""
    status = getattr(pod, "status", None)
    phase = getattr(status, "phase", None)
    statuses = getattr(status, "container_statuses", None) or []

    for cs in statuses:
        state = getattr(cs, "state", None)
        waiting = getattr(state, "waiting", None) if state else None
        if waiting and getattr(waiting, "reason", None) in (
            "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
        ):
            return False, waiting.reason
        last = getattr(cs, "last_state", None)
        terminated = getattr(last, "terminated", None) if last else None
        if terminated and getattr(terminated, "reason", None) == "OOMKilled":
            return False, "OOMKilled"
        if not getattr(cs, "ready", True):
            return False, "container not ready"

    if phase in ("Failed", "Unknown"):
        return False, str(phase)
    if phase == "Pending":
        return False, "Pending"
    return True, "ready"


def _as_selector(selector: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in selector.items())


# Prefixed ids keep kinds from colliding (a pod and configmap could share a name).
def _cm_id(name: str) -> str:
    return f"configmap/{name}"


def _secret_id(name: str) -> str:
    return f"secret/{name}"


def _pvc_id(name: str) -> str:
    return f"pvc/{name}"


def _svc_id(name: str) -> str:
    return f"service/{name}"
