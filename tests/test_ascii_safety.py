"""Regression guard: every string the agent returns over the webhook/incidents
API must be ASCII-only.

Two separate real bugs on the real Cobra cluster were caused by a stray em
dash (``—``) in a user-facing note: once in the "no runbook configured"
message (introduced in 0.3.2, caught and fixed in 0.3.3), and again,
independently, in the unrelated "Correlated: ..." note (introduced in 0.3.4,
caught here). Both showed up as mojibake (``\\udce2\\udc80\\udc94``) when
piped through ``python3 -m json.tool`` on the Cobra jumpserver's non-UTF-8
locale shell. Patching the one string that already bit us wasn't enough —
this test recursively scans the ACTUAL serialized report, so a third
non-ASCII character introduced anywhere in reasoning/detection output gets
caught before it ships, not after the next real-cluster test.
"""
from __future__ import annotations

import json

from rca_agent.config import Settings
from rca_agent.models.alert import Alert
from rca_agent.reasoning.extractive import ExtractivePipeline
from tests.test_event_watcher import _make_multi_watcher


def _assert_ascii(obj, path: str = "$") -> None:
    """Recursively assert every string in a JSON-able structure is ASCII."""
    if isinstance(obj, str):
        non_ascii = [c for c in obj if ord(c) > 127]
        assert not non_ascii, f"non-ASCII character(s) {non_ascii!r} at {path}: {obj!r}"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _assert_ascii(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_ascii(v, f"{path}[{i}]")


def test_demo_incident_report_is_ascii_only():
    """The default demo-mode report (no cluster, no RAG) must be pure ASCII —
    this is the path every fresh install hits first."""
    report = ExtractivePipeline().run(
        Alert(labels={"alertname": "UPFDown", "pod": "upf-0", "namespace": "open5gs"})
    )
    _assert_ascii(json.loads(report.model_dump_json()))


def test_correlated_incident_report_is_ascii_only():
    """The exact code path that broke on the real cluster: the 0.3.4
    correlation note, built from multiple simultaneous incidents."""
    msg = "Readiness probe failed: HTTP probe failed with statuscode: 500"
    specs = [
        {"name": "sm-diameter-a", "reason": "Unhealthy", "message": msg},
        {"name": "sm-sgw-session-b", "reason": "Unhealthy", "message": msg},
    ]
    watcher = _make_multi_watcher(specs)

    reports = watcher.poll_once()

    assert reports, "expected the correlation scenario to produce incidents"
    for report in reports:
        _assert_ascii(json.loads(report.model_dump_json()))


def test_pipeline_cluster_report_is_ascii_only():
    """A cluster-backed report (real KubeQueryTools path, not the stub)."""
    from rca_agent.graph.builder import GraphBuilder
    from tests import fake_kube as fk

    store = {
        "nodes": [fk.node("worker-1")],
        "pods": [fk.pod("upf-7c9-bbbb", node_name="worker-1", healthy=False,
                        oomkilled=True, owner_refs=[fk.owner("upf-7c9")])],
        "events": [fk.event("upf-7c9-bbbb", "OOMKilled", "Container upf was OOMKilled")],
        "logs": {"upf-7c9-bbbb": {"previous": 'level=error msg="out of memory"'}},
        "configmaps": [], "secrets": [], "pvcs": [],
        "replicasets": [fk.replicaset("upf-7c9", "upf", replicas=1)],
        "deployments": [fk.deployment("upf", replicas=1)],
        "services": [],
    }
    cfg = Settings(cluster_enabled=True, namespace="open5gs")
    builder = GraphBuilder(cfg, kube_client=fk.FakeKubeClient(store))
    pipeline = ExtractivePipeline(cfg, builder=builder)

    report = pipeline.run(Alert(labels={"alertname": "HighErrorRate", "pod": "upf-7c9-bbbb",
                                        "namespace": "open5gs", "severity": "critical"}))
    _assert_ascii(json.loads(report.model_dump_json()))
