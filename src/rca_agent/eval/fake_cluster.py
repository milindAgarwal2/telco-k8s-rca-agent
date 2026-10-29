"""A minimal, package-local fake read-only kube client for the eval harness.

Mirrors ``tests/fake_kube.py`` but ships inside the package so the harness runs
standalone (``python -m rca_agent.eval``) in the container, without the tests
directory on the path. Duck-typed via SimpleNamespace — no kubernetes package,
no cluster.
"""
from __future__ import annotations

from types import SimpleNamespace as NS


def _list(items):
    return NS(items=items)


def meta(name, owner_refs=None, labels=None, creation_timestamp=None,
         managed_fields=None):
    return NS(name=name, owner_references=owner_refs or [], labels=labels or {},
              creation_timestamp=creation_timestamp,
              managed_fields=managed_fields or [])


def managed_field(time, manager="kubectl-client-side-apply", operation="Update"):
    return NS(time=time, manager=manager, operation=operation)


def owner(name, kind="ReplicaSet"):
    return NS(name=name, kind=kind)


def pod(name, node_name=None, owner_refs=None, volumes=None, containers=None,
        phase="Running", healthy=True, oomkilled=False, waiting_reason=None,
        labels=None, restart_count=0):
    if containers is None:
        containers = [NS(env_from=[], name="app", image="app:1.0", env=[])]
    state = NS(waiting=NS(reason=waiting_reason) if waiting_reason else None,
               terminated=None, running=None)
    last_state = NS(terminated=NS(reason="OOMKilled") if oomkilled else None)
    container_statuses = [NS(ready=healthy and not oomkilled and not waiting_reason,
                             state=state, last_state=last_state, name="app",
                             restart_count=restart_count)]
    status = NS(phase=phase, container_statuses=container_statuses)
    spec = NS(node_name=node_name, volumes=volumes or [], containers=containers)
    return NS(metadata=meta(name, owner_refs, labels), spec=spec, status=status)


def event(involved_name, reason, message="", etype="Warning", kind="Pod",
          last_timestamp=None):
    return NS(involved_object=NS(name=involved_name, kind=kind),
              reason=reason, message=message, type=etype,
              last_timestamp=last_timestamp, first_timestamp=last_timestamp,
              event_time=last_timestamp, count=1)


def cm_volume(cm_name):
    return NS(config_map=NS(name=cm_name), secret=None, persistent_volume_claim=None)


def secret_volume(secret_name):
    return NS(config_map=None, secret=NS(secret_name=secret_name),
              persistent_volume_claim=None)


def pvc_volume(claim_name):
    return NS(config_map=None, secret=None,
              persistent_volume_claim=NS(claim_name=claim_name))


def env_var(name, value=None, config_map_name=None, config_map_key=None):
    value_from = None
    if config_map_key is not None:
        value_from = NS(config_map_key_ref=NS(name=config_map_name, key=config_map_key))
    return NS(name=name, value=value, value_from=value_from)


def container(name="app", image="app:1.0", env=None, env_from=None):
    return NS(name=name, image=image, env=env or [], env_from=env_from or [])


def _pod_template(images=None):
    containers = [NS(image=img) for img in (images or ["app:1.0"])]
    return NS(spec=NS(containers=containers))


def deployment(name, replicas=1, modified=None, images=None):
    mf = [managed_field(modified)] if modified else None
    return NS(metadata=meta(name, managed_fields=mf),
              spec=NS(replicas=replicas, template=_pod_template(images)),
              status=NS(replicas=replicas))


def replicaset(name, deploy_name, replicas=1, created=None, images=None):
    return NS(metadata=meta(name, owner_refs=[owner(deploy_name, "Deployment")],
                            creation_timestamp=created),
              spec=NS(replicas=replicas, template=_pod_template(images)),
              status=NS(replicas=replicas))


def configmap(name, modified=None, data=None):
    return NS(metadata=meta(name, managed_fields=[managed_field(modified)]
                            if modified else None),
              data=data or {})


def secret(name, modified=None):
    return NS(metadata=meta(name, managed_fields=[managed_field(modified)]
                            if modified else None))


def pvc(name):
    return NS(metadata=meta(name))


def node(name, ready=True):
    return NS(metadata=meta(name),
              status=NS(conditions=[NS(type="Ready",
                                       status="True" if ready else "False")]))


def service(name, selector):
    return NS(metadata=meta(name), spec=NS(selector=selector))


class _CoreV1:
    def __init__(self, store):
        self.s = store

    def list_node(self):
        return _list(self.s.get("nodes", []))

    def list_namespaced_pod(self, ns, label_selector=None):
        pods = self.s.get("pods", [])
        if label_selector:
            pods = [p for p in pods if _match(p, label_selector)]
        return _list(pods)

    def list_namespaced_config_map(self, ns, label_selector=None):
        return _list(self.s.get("configmaps", []))

    def list_namespaced_secret(self, ns, label_selector=None):
        return _list(self.s.get("secrets", []))

    def list_namespaced_persistent_volume_claim(self, ns, label_selector=None):
        return _list(self.s.get("pvcs", []))

    def list_namespaced_service(self, ns, label_selector=None):
        return _list(self.s.get("services", []))

    def list_namespaced_event(self, ns, label_selector=None):
        return _list(self.s.get("events", []))

    def read_namespaced_pod_log(self, name, namespace, container=None,
                                tail_lines=None, previous=False, timestamps=False):
        entry = self.s.get("logs", {}).get(name, {})
        key = "previous" if previous else "current"
        text = entry.get(key)
        if text is None:
            raise RuntimeError(f"no {key} logs for {name}")
        return text


class _AppsV1:
    def __init__(self, store):
        self.s = store

    def list_namespaced_deployment(self, ns, label_selector=None):
        return _list(self.s.get("deployments", []))

    def list_namespaced_stateful_set(self, ns, label_selector=None):
        return _list(self.s.get("statefulsets", []))

    def list_namespaced_daemon_set(self, ns, label_selector=None):
        return _list(self.s.get("daemonsets", []))

    def list_namespaced_replica_set(self, ns, label_selector=None):
        return _list(self.s.get("replicasets", []))


def _match(obj, selector: str) -> bool:
    labels = getattr(obj.metadata, "labels", {}) or {}
    for part in selector.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if labels.get(k) != v:
                return False
    return True


class FakeKubeClient:
    """Duck-typed stand-in for tools.kube_client.KubeClient."""

    def __init__(self, store: dict):
        self.core = _CoreV1(store)
        self.apps = _AppsV1(store)
        self.mode = "fake"


def empty_store() -> dict:
    """A store with every expected key present (so _safe_list never KeyErrors)."""
    return {
        "nodes": [], "pods": [], "configmaps": [], "secrets": [], "pvcs": [],
        "services": [], "events": [], "deployments": [], "statefulsets": [],
        "daemonsets": [], "replicasets": [], "logs": {},
    }
