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
      Service --selects--> pods  [health rolled up from selected pods]
      pods --calls--> services   (see ``_detect_calls_edges`` below)

**``calls`` edges (0.3.5)** — real NF-to-NF topology needs either a maintained
static service map (no authoritative source exists for this stack — guessing
one would fabricate exactly the kind of unsupported claim this project exists
to avoid) or OTel tracing (new infra, not something to stand up on someone
else's cluster unasked). So instead we read the ONE grounded signal already
available via get/list: a container's literal env var values, and the values
of ConfigMaps it mounts or reads via ``envFrom``, scanned for a DNS-boundary
match against another Service's name already in this graph. A pod configured
with e.g. ``VAULT_ADDR=https://eric-cloud-native-backupless-key-management:8200``
gets a cited ``calls`` edge to that Service; a pod with no such reference gets
none. This never invents a dependency — absence of a match means absence of
an edge, not a guess (see PLAN.md Known Issues for the full rationale and the
cases this does and does not cover).

When ``cluster_enabled`` is False (default) we return the demo graph so the rest
of the system runs with no cluster.
"""
from __future__ import annotations

import logging
import re

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
        cm_data = self._add_config_objects(g, kube, ns, sel)
        # Service names are needed BEFORE _add_pods so env/ConfigMap values can
        # be matched against them while scanning pods (see _detect_call_targets).
        # _add_services (below) still does the real node/selects-edge creation;
        # this is just a cheap name-only pre-pass.
        service_names = self._list_service_names(kube, ns, sel)
        self._add_pods(g, kube, ns, sel, cm_data, service_names)  # pods + edges + pod health
        self._add_services(g, kube, ns, sel)
        self._roll_up_workload_health(g)
        self._roll_up_service_health(g)

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

    def _add_config_objects(self, g, kube, ns, sel) -> dict:
        """Returns ``{configmap_name: {key: value}}`` for every ConfigMap
        found — needed by ``_add_pods`` to resolve ``valueFrom.configMapKeyRef``
        and to scan mounted ConfigMap data for service-name references (see
        module docstring). Secret VALUES are deliberately never read/returned
        here — only their existence (for ``mounts`` edges); scanning secret
        payloads for hostnames isn't worth the sensitivity trade-off this
        heuristic would add.
        """
        cm_data: dict[str, dict] = {}
        for cm in _safe_list(
            lambda **kw: kube.core.list_namespaced_config_map(ns, label_selector=sel, **kw),
            "configmaps",
        ):
            g.upsert_node(_cm_id(cm.metadata.name), NodeKind.configmap,
                          display=cm.metadata.name)
            cm_data[cm.metadata.name] = dict(getattr(cm, "data", None) or {})
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
        return cm_data

    def _list_service_names(self, kube, ns, sel) -> set[str]:
        """Bare names of every Service in scope — the match set for
        ``_detect_call_targets``. A cheap, name-only pre-pass; ``_add_services``
        (below) still does the real node/selects-edge creation."""
        return {
            svc.metadata.name
            for svc in _safe_list(
                lambda **kw: kube.core.list_namespaced_service(ns, label_selector=sel, **kw),
                "services",
            )
        }

    def _add_pods(self, g, kube, ns, sel, cm_data: dict, service_names: set[str]) -> None:
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
            mounted_configmaps: set[str] = set()
            for vol in getattr(pod.spec, "volumes", None) or []:
                if getattr(vol, "config_map", None):
                    g.upsert_edge(name, _cm_id(vol.config_map.name), EdgeKind.mounts)
                    mounted_configmaps.add(vol.config_map.name)
                if getattr(vol, "secret", None):
                    sname = getattr(vol.secret, "secret_name", None)
                    if sname:
                        g.upsert_edge(name, _secret_id(sname), EdgeKind.mounts)
                pvc = getattr(vol, "persistent_volume_claim", None)
                if pvc:
                    g.upsert_edge(name, _pvc_id(pvc.claim_name), EdgeKind.mounts)

            # mounts via envFrom (configMapRef / secretRef) on containers, PLUS
            # calls edges detected from literal env var values / resolved
            # configMapKeyRef values (see module docstring).
            for container in getattr(pod.spec, "containers", None) or []:
                for env_from in getattr(container, "env_from", None) or []:
                    if getattr(env_from, "config_map_ref", None):
                        g.upsert_edge(name, _cm_id(env_from.config_map_ref.name),
                                      EdgeKind.mounts)
                        mounted_configmaps.add(env_from.config_map_ref.name)
                    if getattr(env_from, "secret_ref", None):
                        g.upsert_edge(name, _secret_id(env_from.secret_ref.name),
                                      EdgeKind.mounts)

                for env in getattr(container, "env", None) or []:
                    env_name = getattr(env, "name", "?")
                    value = getattr(env, "value", None)
                    if value:
                        _add_call_edges(g, name, value, service_names,
                                        f"env:{env_name}")
                        continue  # a literal value wins over valueFrom
                    value_from = getattr(env, "value_from", None)
                    cm_ref = getattr(value_from, "config_map_key_ref", None) \
                        if value_from else None
                    if cm_ref:
                        resolved = cm_data.get(getattr(cm_ref, "name", None), {}).get(
                            getattr(cm_ref, "key", None))
                        if resolved:
                            _add_call_edges(
                                g, name, resolved, service_names,
                                f"configmap:{cm_ref.name}.{cm_ref.key}",
                            )

            # calls edges from ANY key in a mounted ConfigMap's data (covers
            # config consumed as a mounted file, e.g. a properties/yaml blob,
            # not just an individually-referenced env var).
            for cm_name in mounted_configmaps:
                for key, value in cm_data.get(cm_name, {}).items():
                    _add_call_edges(g, name, value, service_names,
                                    f"configmap:{cm_name}.{key}")

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

    def _roll_up_service_health(self, g: DependencyGraph) -> None:
        """Roll up each Service's health from the pods it selects.

        Without this, a Service node defaults to "healthy" regardless of the
        pods behind it, which would make a ``calls`` edge TO a service
        pointless for upstream-health reasoning (``unhealthy_upstream``).
        """
        for node_id in list(g.graph.nodes):
            if g.graph.nodes[node_id].get("kind") == NodeKind.service.value:
                g.roll_up_service_health(node_id)


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


# ---------------------------------------------------------------------------
# calls-edge detection (0.3.5) — see module docstring for the full rationale.
# ---------------------------------------------------------------------------
_MIN_MATCH_NAME_LEN = 4   # skip implausibly short/generic service names
_BOUNDARY_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _boundary_re(name: str) -> re.Pattern[str]:
    """A boundary-safe regex for ``name`` (cached per name), requiring ``name``
    to be a COMPLETE identifier, not a prefix of a longer hyphenated one.

    Matches ``name`` as a whole token: ``"foo-bar.default.svc.cluster.local"``
    or ``"https://foo-bar:8200"`` match; ``"foo-barbaz"`` does not.

    Plain ``\\b`` is NOT safe here: a hyphen counts as a word boundary, so
    ``\\beric-cm-mediator\\b`` would also match inside
    ``"eric-cm-mediator-tls-client-ca-secret"`` — a DIFFERENT, longer secret
    name that merely starts with the same prefix (a real false positive found
    testing against the Cobra cluster, where nearly every secret/configmap is
    named ``<component>-<descriptor>-secret``). Requiring the character
    immediately before/after the match to be neither alphanumeric nor a
    hyphen treats ``name`` as a complete hyphen-delimited token, never a
    prefix or suffix of a longer one.
    """
    pattern = _BOUNDARY_RE_CACHE.get(name)
    if pattern is None:
        pattern = re.compile(
            r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])"
        )
        _BOUNDARY_RE_CACHE[name] = pattern
    return pattern


def _detect_call_targets(value: str, service_names: set[str]) -> set[str]:
    """Which of ``service_names`` are referenced inside ``value`` as a whole
    token. Grounded, literal text matching only — never a guess."""
    if not value:
        return set()
    return {
        svc for svc in service_names
        if len(svc) >= _MIN_MATCH_NAME_LEN and _boundary_re(svc).search(value)
    }


def _add_call_edges(g: DependencyGraph, pod_name: str, value: str,
                    service_names: set[str], evidence: str) -> None:
    """Add a cited ``calls`` edge from ``pod_name`` to every service
    referenced in ``value``, skipping an obvious self-reference (a pod
    naming its OWN workload, e.g. a "my own address" env var — not a real
    dependency)."""
    for target in _detect_call_targets(value, service_names):
        if pod_name.startswith(target + "-") or pod_name == target:
            continue  # self-reference, not a dependency
        g.upsert_edge(pod_name, _svc_id(target), EdgeKind.calls, evidence=evidence)
