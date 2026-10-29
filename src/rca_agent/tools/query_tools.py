"""Read-only query tools.

These are the ONLY way the agent touches the cluster. There is deliberately no
write/patch/delete tool — safety is enforced by the absence of a capability and
by RBAC (get/list/watch only). The interface is pluggable: a ``StubQueryTools``
implementation returns deterministic demo data (no cluster), and a future
``KubeQueryTools`` will use the read-only kubernetes client.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from rca_agent.models.alert import KubeEvent


def _now() -> datetime:
    return datetime.now(timezone.utc)


class QueryTools(ABC):
    """Abstract read-only interface over cluster state."""

    @abstractmethod
    def pod_status(self, resource: str, namespace: str) -> dict:
        """Phase, container statuses, restart counts, reasons for a resource."""

    @abstractmethod
    def recent_events(self, resource: str, namespace: str,
                      since_minutes: int = 30) -> list[KubeEvent]:
        """Recent Kubernetes events for a resource."""

    @abstractmethod
    def logs(self, resource: str, namespace: str, tail_lines: int = 200) -> list[str]:
        """Last N log lines for a resource (treated as untrusted data)."""

    @abstractmethod
    def metrics(self, promql: str, namespace: str) -> dict:
        """Point/range result of a PromQL query."""

    @abstractmethod
    def recent_changes(self, namespace: str, since_minutes: int = 15) -> list[dict]:
        """Rollouts, ConfigMap/Secret updates, image changes, node/scaling events."""


class StubQueryTools(QueryTools):
    """Deterministic demo data — lets the whole pipeline run with no cluster.

    The default scenario mirrors the plan's headline example: the UPF pod was
    OOMKilled shortly after a ConfigMap memory-limit change, which cascades into
    SMF errors.
    """

    def pod_status(self, resource: str, namespace: str) -> dict:
        if resource and "upf" in resource.lower():
            return {
                "resource": resource,
                "phase": "Running",
                "ready": False,
                "restart_count": 5,
                "last_termination_reason": "OOMKilled",
                "containers": [{"name": "upf", "ready": False, "reason": "OOMKilled"}],
            }
        return {
            "resource": resource,
            "phase": "Running",
            "ready": True,
            "restart_count": 0,
            "containers": [{"name": resource or "app", "ready": True}],
        }

    def recent_events(self, resource: str, namespace: str,
                      since_minutes: int = 30) -> list[KubeEvent]:
        if resource and "upf" in resource.lower():
            return [
                KubeEvent(
                    reason="OOMKilled",
                    message="Container upf was OOMKilled (memory limit exceeded)",
                    kind="Pod",
                    name=resource,
                    namespace=namespace,
                    event_type="Warning",
                    last_seen=_now() - timedelta(minutes=2),
                    count=5,
                )
            ]
        return []

    def logs(self, resource: str, namespace: str, tail_lines: int = 200) -> list[str]:
        if resource and "upf" in resource.lower():
            return [
                "level=error msg=\"out of memory: cannot allocate session buffer\"",
                "level=fatal msg=\"gtp-u context allocation failed\"",
            ]
        if resource and "smf" in resource.lower():
            return [
                "level=error msg=\"PFCP association down: UPF unreachable\"",
                "level=error msg=\"session establishment failed: no UPF\"",
            ]
        return ["level=info msg=\"service healthy\""]

    def metrics(self, promql: str, namespace: str) -> dict:
        return {"query": promql, "namespace": namespace, "result": [], "stub": True}

    def recent_changes(self, namespace: str, since_minutes: int = 15) -> list[dict]:
        return [
            {
                "type": "configmap_update",
                "object": "upf-config",
                "namespace": namespace,
                "detail": "resources.limits.memory lowered 2Gi -> 512Mi",
                "at": (_now() - timedelta(minutes=4)).isoformat(),
                "actor": "kubectl-edit",
                "actor_source": "human (kubectl)",
                "is_automation": False,
                "operation": "Update",
            }
        ]


# ---------------------------------------------------------------------------
# Real cluster implementation (read-only).
# ---------------------------------------------------------------------------
logger = logging.getLogger("rca_agent.tools")


class KubeQueryTools(QueryTools):
    """Read-only query tools backed by the kubernetes client.

    Every method is a ``get``/``list``/``read`` call — there is no mutating
    capability here, matching the get/list/watch RBAC. All calls are wrapped so
    a permission error (403) or missing resource degrades gracefully (empty
    result + warning) instead of crashing the reasoning pipeline.

    ``resource`` is resolved leniently to the concrete pod(s) it refers to: an
    exact pod name, a workload/prefix match (``upf`` -> ``upf-7c9-abc``), or a
    graph id like ``service/foo`` (the ``service/`` prefix is stripped). This
    mirrors how the alert ``target`` and graph node ids flow in.
    """

    def __init__(self, kube_client=None, prometheus_url: str | None = None,
                 kubeconfig_mode: str = "auto") -> None:
        self._kube = kube_client
        self._prometheus_url = prometheus_url.rstrip("/") if prometheus_url else None
        self._kubeconfig_mode = kubeconfig_mode

    # -- client bootstrap (lazy) -------------------------------------------
    def _client(self):
        if self._kube is None:
            from rca_agent.tools.kube_client import build_kube_client
            self._kube = build_kube_client(self._kubeconfig_mode)
        return self._kube

    # -- resource resolution ------------------------------------------------
    @staticmethod
    def _bare_name(resource: str) -> str:
        """Strip a graph-id prefix (``service/x`` -> ``x``)."""
        return resource.split("/", 1)[1] if "/" in resource else resource

    def _resolve_pods(self, resource: str, namespace: str) -> list:
        """Return the pod objects a ``resource`` refers to (best effort).

        Order of preference:
          1. exact pod-name match,
          2. pods whose name starts with ``<resource>-`` (workload -> pods),
          3. empty list (caller treats as unknown).
        """
        name = self._bare_name(resource)
        pods = _safe_list(
            lambda: self._client().core.list_namespaced_pod(namespace),
            "pods",
        )
        exact = [p for p in pods if _obj_name(p) == name]
        if exact:
            return exact
        prefix = [p for p in pods if _obj_name(p).startswith(name + "-")]
        if prefix:
            return prefix
        # last resort: loose substring (helps alerts that carry a short app name)
        loose = [p for p in pods if name and name in _obj_name(p)]
        return loose

    # -- QueryTools interface ----------------------------------------------
    def pod_status(self, resource: str, namespace: str) -> dict:
        pods = self._resolve_pods(resource, namespace)
        if not pods:
            return {"resource": resource, "phase": "Unknown", "ready": True,
                    "restart_count": 0, "containers": [], "note": "pod not found"}
        # Report the worst pod (prefer one that is not ready / has restarts).
        worst = min(pods, key=_pod_health_rank)
        return _pod_status_dict(worst, resource)

    def recent_events(self, resource: str, namespace: str,
                      since_minutes: int = 30) -> list[KubeEvent]:
        name = self._bare_name(resource)
        # Names of the resolved pods so we can match involvedObject exactly.
        pod_names = {_obj_name(p) for p in self._resolve_pods(resource, namespace)}
        pod_names.add(name)
        cutoff = _now() - timedelta(minutes=since_minutes)

        raw = _safe_list(
            lambda: self._client().core.list_namespaced_event(namespace),
            "events",
        )
        out: list[KubeEvent] = []
        for ev in raw:
            involved = getattr(ev, "involved_object", None)
            iname = getattr(involved, "name", None) if involved else None
            # Match the involved object to our resource (exact or prefix).
            if iname not in pod_names and not (
                iname and name and iname.startswith(name)
            ):
                continue
            last = _event_time(ev)
            if last and last < cutoff:
                continue
            out.append(KubeEvent(
                reason=getattr(ev, "reason", "") or "",
                message=getattr(ev, "message", "") or "",
                kind=getattr(involved, "kind", None) if involved else None,
                name=iname,
                namespace=namespace,
                event_type=getattr(ev, "type", "Warning") or "Warning",
                first_seen=_to_dt(getattr(ev, "first_timestamp", None)),
                last_seen=last,
                count=getattr(ev, "count", 1) or 1,
            ))
        # Warnings first, then most recent.
        out.sort(key=lambda e: (e.event_type != "Warning",
                                -(e.last_seen.timestamp() if e.last_seen else 0)))
        return out

    def logs(self, resource: str, namespace: str, tail_lines: int = 200) -> list[str]:
        pods = self._resolve_pods(resource, namespace)
        lines: list[str] = []
        for pod in pods[:3]:  # cap: avoid pulling logs for a huge fan-out
            pname = _obj_name(pod)
            for container in _container_names(pod):
                # Prefer previous logs for a crashed container (they hold the
                # actual failure); fall back to current.
                for previous in (True, False):
                    try:
                        text = self._client().core.read_namespaced_pod_log(
                            name=pname, namespace=namespace, container=container,
                            tail_lines=tail_lines, previous=previous,
                            timestamps=False,
                        )
                    except Exception as exc:  # noqa: BLE001
                        if previous:
                            continue  # no previous logs -> try current
                        logger.warning("cannot read logs for %s/%s: %s",
                                       pname, container, _err(exc))
                        text = ""
                    if text:
                        for ln in text.splitlines():
                            lines.append(f"[{pname}/{container}] {ln}")
                        break  # got logs for this container
        return lines[: max(tail_lines, 1) * 2]

    def metrics(self, promql: str, namespace: str) -> dict:
        """Query Prometheus if configured; otherwise return an empty result.

        Metrics are optional for root-cause: pod status / events / logs /
        changes already carry the signal. When no Prometheus URL is set we
        return a well-formed empty result so callers never special-case it.
        """
        if not self._prometheus_url:
            return {"query": promql, "namespace": namespace, "result": [],
                    "available": False, "note": "no prometheus_url configured"}
        try:
            import urllib.parse
            import urllib.request

            url = (f"{self._prometheus_url}/api/v1/query?"
                   + urllib.parse.urlencode({"query": promql}))
            with urllib.request.urlopen(url, timeout=5) as resp:
                import json
                data = json.loads(resp.read().decode("utf-8"))
            result = data.get("data", {}).get("result", [])
            return {"query": promql, "namespace": namespace, "result": result,
                    "available": True}
        except Exception as exc:  # noqa: BLE001
            logger.warning("prometheus query failed: %s", _err(exc))
            return {"query": promql, "namespace": namespace, "result": [],
                    "available": False, "error": _err(exc)}

    def recent_changes(self, namespace: str, since_minutes: int = 15) -> list[dict]:
        """Detect what changed in the window: config/secret edits, rollouts,
        new ReplicaSet revisions, and scaling — the cheapest candidate causes.
        """
        cutoff = _now() - timedelta(minutes=since_minutes)
        changes: list[dict] = []
        kube = self._client()

        # 1) ConfigMap / Secret updates. Use the REAL last-edit time
        #    (managedFields[].time) only — NOT creation time — so long-lived
        #    objects don't look "recently changed". Also skip HA bookkeeping
        #    objects (Postgres leader-election, TLS supervisor state) that are
        #    rewritten constantly and are never an application-config cause.
        for cm in _safe_list(
            lambda: kube.core.list_namespaced_config_map(namespace), "configmaps"
        ):
            name = _obj_name(cm)
            if _is_ha_bookkeeping(name):
                continue
            ts, mgr, op = _managed_fields_actor(cm)
            if ts and ts >= cutoff:
                changes.append(_change("configmap_update", name, namespace,
                                       "configmap updated", ts, mgr, op))
        for sec in _safe_list(
            lambda: kube.core.list_namespaced_secret(namespace), "secrets"
        ):
            name = _obj_name(sec)
            if _is_ha_bookkeeping(name):
                continue
            ts, mgr, op = _managed_fields_actor(sec)
            if ts and ts >= cutoff:
                changes.append(_change("secret_update", name, namespace,
                                       "secret updated", ts, mgr, op))

        # 2) New ReplicaSet revisions (a rollout/image change creates a new RS).
        for rs in _safe_list(
            lambda: kube.apps.list_namespaced_replica_set(namespace), "replicasets"
        ):
            created = _to_dt(_creation_ts(rs))
            if created and created >= cutoff:
                owner_name = _first_owner_name(rs)
                images = _pod_template_images(rs)
                detail = ("rollout/new ReplicaSet"
                          + (f" (images: {', '.join(images)})" if images else ""))
                _t, mgr, op = _managed_fields_actor(rs)
                changes.append(_change("rollout", owner_name or _obj_name(rs),
                                       namespace, detail, created, mgr, op))

        # 3) Deployments/StatefulSets whose spec changed recently (generation bump
        #    reflected in a recent managedFields update on the spec).
        for dep in _safe_list(
            lambda: kube.apps.list_namespaced_deployment(namespace), "deployments"
        ):
            ts, mgr, op = _managed_fields_actor(dep)
            if ts is None:
                ts = _last_modified(dep)
            if ts and ts >= cutoff:
                images = _pod_template_images(dep)
                detail = ("deployment spec updated"
                          + (f" (images: {', '.join(images)})" if images else ""))
                changes.append(_change("deployment_update", _obj_name(dep),
                                       namespace, detail, ts, mgr, op))

        # De-dup by (type, object) keeping the most recent, then sort newest first.
        dedup: dict[tuple, dict] = {}
        for ch in changes:
            key = (ch["type"], ch["object"])
            if key not in dedup or ch["at"] > dedup[key]["at"]:
                dedup[key] = ch
        out = sorted(dedup.values(), key=lambda c: c["at"], reverse=True)
        return out


# ---------------------------------------------------------------------------
# Helpers for reading the kube object model (tolerant of real + fake objects).
# ---------------------------------------------------------------------------
def _obj_name(obj) -> str:
    return getattr(getattr(obj, "metadata", None), "name", "") or ""


def _safe_list(call, label: str):
    """Call a kube ``list_*`` function, tolerating permission/API errors."""
    try:
        result = call()
        return getattr(result, "items", None) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("skipping %s: cannot list (%s)", label, _err(exc))
        return []


def _err(exc: Exception) -> str:
    status = getattr(exc, "status", None)
    reason = getattr(exc, "reason", None) or type(exc).__name__
    return f"{status} {reason}".strip()


def _container_names(pod) -> list[str]:
    spec = getattr(pod, "spec", None)
    containers = getattr(spec, "containers", None) or []
    names = [getattr(c, "name", None) for c in containers]
    return [n for n in names if n] or [None]  # None -> let API pick the default


def _pod_status_dict(pod, resource: str) -> dict:
    status = getattr(pod, "status", None)
    phase = getattr(status, "phase", None) or "Unknown"
    statuses = getattr(status, "container_statuses", None) or []
    ready = bool(statuses) and all(getattr(cs, "ready", False) for cs in statuses)
    restart_count = sum(getattr(cs, "restart_count", 0) or 0 for cs in statuses)
    last_reason = None
    containers = []
    for cs in statuses:
        c_ready = getattr(cs, "ready", False)
        reason = None
        state = getattr(cs, "state", None)
        waiting = getattr(state, "waiting", None) if state else None
        if waiting and getattr(waiting, "reason", None):
            reason = waiting.reason
        last = getattr(cs, "last_state", None)
        terminated = getattr(last, "terminated", None) if last else None
        if terminated and getattr(terminated, "reason", None):
            reason = terminated.reason
            last_reason = last_reason or terminated.reason
        containers.append({"name": getattr(cs, "name", "?"), "ready": c_ready,
                           "reason": reason,
                           "restart_count": getattr(cs, "restart_count", 0) or 0})
    return {
        "resource": resource,
        "pod": _obj_name(pod),
        "phase": phase,
        "ready": ready,
        "restart_count": restart_count,
        "last_termination_reason": last_reason,
        "containers": containers,
    }


def _pod_health_rank(pod) -> int:
    """Lower = worse. Used to pick the most-degraded pod among matches."""
    s = _pod_status_dict(pod, _obj_name(pod))
    rank = 0
    if s["last_termination_reason"]:
        rank -= 100
    if not s["ready"]:
        rank -= 50
    rank -= s["restart_count"]
    return rank


def _event_time(ev):
    return (_to_dt(getattr(ev, "last_timestamp", None))
            or _to_dt(getattr(ev, "event_time", None))
            or _to_dt(getattr(ev, "first_timestamp", None)))


def _to_dt(value):
    """Normalize a kube timestamp (datetime or ISO string) to aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _creation_ts(obj):
    return getattr(getattr(obj, "metadata", None), "creation_timestamp", None)


def _last_modified(obj):
    """Best-effort last-change time: newest managedFields time, else creation.

    A ``kubectl apply`` / edit updates ``managedFields[].time``; that is the most
    reliable "when did this object last change" signal without the audit log.
    """
    meta = getattr(obj, "metadata", None)
    times = []
    for mf in getattr(meta, "managed_fields", None) or []:
        t = _to_dt(getattr(mf, "time", None))
        if t:
            times.append(t)
    if times:
        return max(times)
    return _to_dt(_creation_ts(obj))


# Substrings of objects that are HA / control-plane bookkeeping (leader
# election, TLS supervisor state, kvdb replication). These are rewritten
# constantly by operators and are never an application-config root cause, so we
# exclude them from change-correlation to keep the signal clean.
_HA_BOOKKEEPING_MARKERS = (
    "-db-pg-leader",   # Postgres leader-election (eric-*-db-pg-leader)
    "-tls-ha",         # sip-tls HA state
    "-supervisor-ha",  # sip-tls supervisor HA state
    "leader-election",
    "leaderelection",
)


def _is_ha_bookkeeping(name: str) -> bool:
    n = (name or "").lower()
    return any(marker in n for marker in _HA_BOOKKEEPING_MARKERS)


def _first_owner_name(obj):
    refs = getattr(getattr(obj, "metadata", None), "owner_references", None) or []
    return getattr(refs[0], "name", None) if refs else None


def _pod_template_images(workload) -> list[str]:
    spec = getattr(workload, "spec", None)
    template = getattr(spec, "template", None)
    tspec = getattr(template, "spec", None)
    containers = getattr(tspec, "containers", None) or []
    return [getattr(c, "image", "") for c in containers if getattr(c, "image", None)]


def _managed_fields_actor(obj) -> tuple[datetime | None, str | None, str | None]:
    """Return ``(time, manager, operation)`` for the NEWEST managedFields entry.

    ``manager`` is the tool/controller that made the last edit (e.g.
    ``kubectl-edit``, ``helm``, ``argocd-application-controller``) -- the
    human-vs-automation signal. ``operation`` is ``Update``/``Apply``. All None
    when the object has no managedFields.
    """
    meta = getattr(obj, "metadata", None)
    newest_t: datetime | None = None
    manager: str | None = None
    operation: str | None = None
    for mf in getattr(meta, "managed_fields", None) or []:
        t = _to_dt(getattr(mf, "time", None))
        if t and (newest_t is None or t > newest_t):
            newest_t = t
            manager = getattr(mf, "manager", None)
            operation = getattr(mf, "operation", None)
    return newest_t, manager, operation


# Prefix -> (human-readable source, is_automation). First match wins; the raw
# manager string is always kept too, so classification never hides the truth.
_ACTOR_RULES = [
    ("kubectl", ("human (kubectl)", False)),
    ("oc", ("human (oc)", False)),
    ("helm", ("Helm", True)),
    ("argocd", ("GitOps (Argo CD)", True)),
    ("flux", ("GitOps (Flux)", True)),
    ("kustomize", ("GitOps (Kustomize)", True)),
    ("kube-controller-manager", ("controller", True)),
]


def _classify_actor(manager: str | None) -> tuple[str, bool | None]:
    """Map a managedFields manager to ``(source_label, is_automation)``.

    ``is_automation`` is True/False for recognized tools, None when unknown.
    """
    if not manager:
        return "unknown", None
    m = manager.lower()
    for prefix, (label, auto) in _ACTOR_RULES:
        if m.startswith(prefix):
            return label, auto
    if m.endswith(("-controller", "-operator")) or "operator" in m or "controller" in m:
        return "controller/operator", True
    return manager, None  # unknown: show verbatim


def _change(ctype: str, obj: str, ns: str, detail: str, at: datetime,
            manager: str | None = None, operation: str | None = None) -> dict:
    source, is_automation = _classify_actor(manager)
    return {"type": ctype, "object": obj, "namespace": ns, "detail": detail,
            "at": at.isoformat(), "actor": manager, "actor_source": source,
            "is_automation": is_automation, "operation": operation}


def get_query_tools(cluster_enabled: bool, kube_client=None,
                    prometheus_url: str | None = None) -> QueryTools:
    """Factory: real read-only kube tools when enabled, stub otherwise.

    ``kube_client`` may be injected (a ``KubeClient`` or any object exposing
    read-only ``core``/``apps`` APIs) — used by tests with a fake client. When
    None and the cluster is enabled, a real read-only client is built lazily.
    ``prometheus_url`` enables the PromQL path; when unset, ``metrics`` returns
    an empty (but well-formed) result instead of failing.
    """
    if not cluster_enabled:
        return StubQueryTools()
    return KubeQueryTools(kube_client=kube_client, prometheus_url=prometheus_url)
