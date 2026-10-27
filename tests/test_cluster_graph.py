"""Cluster-free tests for GraphBuilder._rebuild_from_cluster via a fake client."""
from __future__ import annotations

from rca_agent.config import Settings
from rca_agent.graph.builder import GraphBuilder
from rca_agent.graph.dependency_graph import EdgeKind, Health, NodeKind
from tests import fake_kube as fk


def _settings(selector="") -> Settings:
    return Settings(cluster_enabled=True, namespace="open5gs", nf_selector=selector)


def _store_upf(pod_specs):
    """A UPF app: Deployment -> ReplicaSet -> N pods, a configmap, a node, a service."""
    return {
        "nodes": [fk.node("worker-1"), fk.node("worker-2")],
        "deployments": [fk.deployment("upf", replicas=len(pod_specs))],
        "replicasets": [fk.replicaset("upf-7c9", "upf", replicas=len(pod_specs))],
        "configmaps": [fk.configmap("upf-config")],
        "secrets": [fk.secret("upf-secret")],
        "pvcs": [fk.pvc("upf-data")],
        "services": [fk.service("upf", selector={"app": "upf"})],
        "pods": pod_specs,
    }


def _upf_pod(name, **kw):
    return fk.pod(
        name,
        node_name=kw.pop("node_name", "worker-1"),
        owner_refs=[fk.owner("upf-7c9", "ReplicaSet")],
        volumes=[fk.cm_volume("upf-config"), fk.secret_volume("upf-secret"),
                 fk.pvc_volume("upf-data")],
        labels={"app": "upf"},
        **kw,
    )


def _build(store, selector=""):
    b = GraphBuilder(_settings(selector), kube_client=fk.FakeKubeClient(store))
    return b.rebuild()


def test_discovers_pods_nodes_and_workload():
    g = _build(_store_upf([_upf_pod("upf-0"), _upf_pod("upf-1", node_name="worker-2")]))
    assert g.node("upf-0") and g.node("upf-0")["kind"] == NodeKind.pod.value
    assert g.node("upf") and g.node("upf")["kind"] == NodeKind.deployment.value
    assert g.node("worker-1")["kind"] == NodeKind.node.value


def test_builds_runs_on_managed_by_and_mounts_edges():
    g = _build(_store_upf([_upf_pod("upf-0")]))
    gg = g.graph
    assert gg.has_edge("upf-0", "worker-1", key=EdgeKind.runs_on.value)
    assert gg.has_edge("upf-0", "upf-7c9", key=EdgeKind.managed_by.value)
    assert gg.has_edge("upf-7c9", "upf", key=EdgeKind.managed_by.value)
    assert gg.has_edge("upf-0", "configmap/upf-config", key=EdgeKind.mounts.value)
    assert gg.has_edge("upf-0", "secret/upf-secret", key=EdgeKind.mounts.value)
    assert gg.has_edge("upf-0", "pvc/upf-data", key=EdgeKind.mounts.value)


def test_service_selects_pods():
    g = _build(_store_upf([_upf_pod("upf-0")]))
    assert g.graph.has_edge("service/upf", "upf-0", key=EdgeKind.selects.value)


def test_health_rollup_all_healthy():
    g = _build(_store_upf([_upf_pod("upf-0"), _upf_pod("upf-1")]))
    assert g.node("upf")["health"] == Health.healthy.value


def test_health_rollup_degraded_when_one_pod_oomkilled():
    g = _build(_store_upf([
        _upf_pod("upf-0"),
        _upf_pod("upf-1", oomkilled=True, healthy=False),
        _upf_pod("upf-2"),
    ]))
    # 2 of 3 ready -> degraded (replicas absorbing the loss)
    assert g.node("upf")["health"] == Health.degraded.value
    assert g.node("upf-1")["health_reason"] == "OOMKilled"
    assert not g.is_healthy("upf-1")


def test_health_rollup_down_when_all_pods_unhealthy():
    g = _build(_store_upf([
        _upf_pod("upf-0", oomkilled=True, healthy=False),
        _upf_pod("upf-1", waiting_reason="CrashLoopBackOff", healthy=False),
    ]))
    assert g.node("upf")["health"] == Health.down.value


def test_empty_selector_scopes_whole_namespace():
    # Two different apps in the namespace; empty selector keeps both.
    store = _store_upf([_upf_pod("upf-0")])
    store["pods"].append(fk.pod("amf-0", node_name="worker-1", labels={"app": "amf"}))
    g = _build(store, selector="")
    assert g.node("upf-0") and g.node("amf-0")


def test_label_selector_narrows_to_one_app():
    store = _store_upf([_upf_pod("upf-0")])
    store["pods"].append(fk.pod("amf-0", node_name="worker-1", labels={"app": "amf"}))
    g = _build(store, selector="app=upf")
    assert g.node("upf-0")
    assert g.node("amf-0") is None  # filtered out by the selector


def test_safe_list_paginates_via_continue_and_forwards_timeout():
    """Large-namespace lists are chunked server-side via limit/_continue and
    bounded by a per-request timeout, so one unbounded list cannot hang."""
    from types import SimpleNamespace as NS

    from rca_agent.graph import builder as B

    pages = {
        None: NS(items=[NS(name="a"), NS(name="b")], metadata=NS(_continue="t1")),
        "t1": NS(items=[NS(name="c")], metadata=NS(_continue=None)),
    }
    seen = []

    def paging_list(**kw):
        seen.append(kw)
        return pages[kw.get("_continue")]

    items = B._safe_list(paging_list, "things")
    assert [i.name for i in items] == ["a", "b", "c"]
    assert all(c.get("limit") == B._LIST_PAGE_SIZE for c in seen)
    assert all(c.get("_request_timeout") == B._LIST_REQUEST_TIMEOUT for c in seen)


def test_safe_list_falls_back_when_call_rejects_kwargs():
    """A simple callable that doesn't accept pagination kwargs still works."""
    from types import SimpleNamespace as NS

    from rca_agent.graph import builder as B

    def strict(**kw):
        if kw:
            raise TypeError("no kwargs")
        return NS(items=[NS(name="x")], metadata=None)

    items = B._safe_list(strict, "strict")
    assert [i.name for i in items] == ["x"]


# ---------------------------------------------------------------------------
# calls-edge detection (0.3.5) — grounded in literal env var / ConfigMap
# values, never a fabricated service map. See graph/builder.py module
# docstring and PLAN.md Known Issues for the full rationale.
#
# NB: service/workload names here are deliberately >= 4 chars (e.g.
# "upf-app", "smf-app", not bare "upf"/"smf") to exercise the real
# ``_MIN_MATCH_NAME_LEN`` guard the same way real (long, hyphenated)
# cluster service names do — a 3-char name would be silently filtered by
# that same guard and make these tests misleading.
# ---------------------------------------------------------------------------
def _two_app_store(caller_env=None, caller_env_from=None, dep_healthy=True, cm_data=None):
    """``upf-app`` is the caller (one pod, custom containers); ``smf-app`` is
    the dependency (one pod, whose health rolls up onto ``service/smf-app``)."""
    caller_pod = fk.pod(
        "upf-app-0", node_name="worker-1",
        owner_refs=[fk.owner("upf-app-7c9", "ReplicaSet")],
        containers=[fk.container(env=caller_env or [], env_from=caller_env_from or [])],
        labels={"app": "upf-app"},
    )
    dep_pod = fk.pod(
        "smf-app-0", node_name="worker-1", healthy=dep_healthy,
        waiting_reason=None if dep_healthy else "CrashLoopBackOff",
        owner_refs=[fk.owner("smf-app-rs", "ReplicaSet")],
        labels={"app": "smf-app"},
    )
    return {
        "nodes": [fk.node("worker-1")],
        "deployments": [fk.deployment("upf-app", replicas=1),
                        fk.deployment("smf-app", replicas=1)],
        "replicasets": [fk.replicaset("upf-app-7c9", "upf-app", replicas=1),
                        fk.replicaset("smf-app-rs", "smf-app", replicas=1)],
        "configmaps": [fk.configmap("upf-app-config", data=cm_data or {})],
        "secrets": [], "pvcs": [],
        "services": [fk.service("upf-app", selector={"app": "upf-app"}),
                     fk.service("smf-app", selector={"app": "smf-app"})],
        "pods": [caller_pod, dep_pod],
    }


def test_calls_edge_from_literal_env_value_matching_a_service_name():
    store = _two_app_store(caller_env=[fk.env_var("SMF_ADDR", value="smf-app")])
    g = _build(store)
    assert g.graph.has_edge("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)
    edge = g.graph.get_edge_data("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)
    assert edge["evidence"] == "env:SMF_ADDR"


def test_calls_edge_not_created_for_substring_without_a_boundary():
    """"smf-appbackup-host" contains "smf-app" but not as a whole token."""
    store = _two_app_store(caller_env=[fk.env_var("NOISE", value="smf-appbackup-host")])
    g = _build(store)
    assert not g.graph.has_edge("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)


def test_calls_edge_not_created_when_service_name_is_a_prefix_of_a_longer_hyphenated_name():
    """Real-cluster regression: a secret cert path like
    "/run/secrets/smf-app-tls-client-ca-secret/ca.crt" CONTAINS the service
    name "smf-app" followed by a hyphen — plain ``\\b`` treats a hyphen as a
    word boundary and would wrongly match this as a reference to the
    "smf-app" SERVICE, when it's actually the start of a different, longer
    secret name ("smf-app-tls-client-ca-secret"). Found live: nearly every
    pod in the real namespace mounts a `<component>-...-secret` path whose
    prefix coincidentally matches an unrelated real service name, producing
    false "calls" edges across almost the whole graph."""
    store = _two_app_store(caller_env=[fk.env_var(
        "CM_MEDIATOR_CA_CERT", value="/run/secrets/smf-app-tls-client-ca-secret/ca.crt")])
    g = _build(store)
    assert not g.graph.has_edge("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)


def test_calls_edge_matches_as_a_whole_dns_token():
    """A realistic FQDN-shaped value still matches ("smf-app" bounded by dots)."""
    store = _two_app_store(caller_env=[fk.env_var(
        "SMF_URL", value="https://smf-app.open5gs.svc.cluster.local:8080")])
    g = _build(store)
    assert g.graph.has_edge("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)


def test_calls_edge_from_resolved_configmap_key_ref():
    store = _two_app_store(
        cm_data={"smf_host": "smf-app"},
        caller_env=[fk.env_var("SMF_HOST", config_map_name="upf-app-config",
                               config_map_key="smf_host")],
    )
    g = _build(store)
    assert g.graph.has_edge("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)
    edge = g.graph.get_edge_data("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)
    assert edge["evidence"] == "configmap:upf-app-config.smf_host"


def test_calls_edge_from_any_key_in_a_mounted_configmap():
    """Covers config consumed as a mounted blob, not an individually
    referenced env var — any key in a mounted ConfigMap's data is scanned."""
    store = _two_app_store(cm_data={"endpoints.yaml": "upstream: smf-app:8080"},
                           caller_env_from=[fk.configmap_ref("upf-app-config")])
    g = _build(store)
    assert g.graph.has_edge("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)
    edge = g.graph.get_edge_data("upf-app-0", "service/smf-app", key=EdgeKind.calls.value)
    assert edge["evidence"] == "configmap:upf-app-config.endpoints.yaml"


def test_calls_edge_self_reference_is_excluded():
    """A pod naming its OWN workload (e.g. a "my address" env var) is not a
    dependency on itself."""
    store = _two_app_store(caller_env=[fk.env_var("SELF_HOST", value="upf-app")])
    g = _build(store)
    assert not g.graph.has_edge("upf-app-0", "service/upf-app", key=EdgeKind.calls.value)


def test_service_health_rolls_up_from_selected_pods():
    store = _two_app_store(dep_healthy=False)
    g = _build(store)
    assert g.node("service/smf-app")["health"] == Health.down.value


def test_service_health_healthy_when_all_selected_pods_ready():
    store = _two_app_store(dep_healthy=True)
    g = _build(store)
    assert g.node("service/smf-app")["health"] == Health.healthy.value


def test_unhealthy_upstream_found_via_calls_edge_to_unhealthy_service():
    """End-to-end: a real calls edge + a real service-health rollup lets
    graph_walk's unhealthy_upstream() actually name the shared dependency —
    the gap the real eric-pc-sm-* outage exposed (see PLAN.md)."""
    store = _two_app_store(caller_env=[fk.env_var("SMF_ADDR", value="smf-app")],
                           dep_healthy=False)
    g = _build(store)
    assert "service/smf-app" in g.unhealthy_upstream("upf-app-0")
    assert g.calls_edge_evidence("upf-app-0", "service/smf-app") == "env:SMF_ADDR"


def test_403_on_a_resource_is_non_fatal():
    """A 403 listing one resource type (e.g. cluster-scoped nodes) must not
    blank the whole graph — the rest of the build proceeds."""
    store = _store_upf([_upf_pod("upf-0")])
    client = fk.FakeKubeClient(store)

    class _ApiErr(Exception):
        status = 403
        reason = "Forbidden"

    def _boom(*a, **k):
        raise _ApiErr()

    client.core.list_node = _boom  # forbidden, like a namespace-scoped token

    b = GraphBuilder(_settings(), kube_client=client)
    g = b.rebuild()
    assert g.stats()["nodes"] > 0  # pods/workloads still discovered
    assert g.node("upf-0") is not None
