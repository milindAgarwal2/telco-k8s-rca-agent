"""API tests for the FastAPI webhook."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from rca_agent.webhook.app import app

client = TestClient(app)
FIXTURE = Path(__file__).parent / "fixtures" / "alertmanager_sample.json"


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_graph_stats():
    r = client.get("/graph/stats")
    assert r.status_code == 200
    assert r.json()["nodes"] > 0


def test_alertmanager_webhook_produces_report():
    payload = json.loads(FIXTURE.read_text())
    r = client.post("/webhook/alertmanager", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["received"] == 1
    assert body["processed"] == 1
    report = body["reports"][0]
    assert report["symptom"]
    assert report["hypotheses"], "expected ranked hypotheses"
    assert report["suggested_next_steps"]


def test_manually_posted_incident_shows_up_in_incidents_list():
    """A webhook-posted alert must land in the same /incidents pool as
    auto-detected ones (0.3.4: shared timeline for correlation)."""
    payload = json.loads(FIXTURE.read_text())
    posted = client.post("/webhook/alertmanager", json=payload).json()
    incident_id = posted["reports"][0]["incident_id"]

    r = client.get("/incidents")
    assert r.status_code == 200
    ids = {i["incident_id"] for i in r.json()["incidents"]}
    assert incident_id in ids

    r = client.get(f"/incidents/{incident_id}")
    assert r.status_code == 200
    assert r.json()["incident_id"] == incident_id


def test_incidents_endpoints_basic():
    r = client.get("/incidents")
    assert r.status_code == 200
    assert "count" in r.json()

    r = client.get("/incidents/does-not-exist")
    assert r.status_code == 404


def test_graph_view_returns_html():
    r = client.get("/graph/view")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "vis-network" in r.text or "DataSet" in r.text


def test_graph_view_node_neighborhood():
    r = client.get("/graph/view/upf?radius=2")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_graph_view_missing_node_404():
    r = client.get("/graph/view/nope-not-here")
    assert r.status_code == 404


def test_startup_does_not_block_on_graph_build(monkeypatch):
    """The initial graph build must run in the background, not block startup.

    A large-namespace cluster build can be slow; if it ran synchronously in the
    lifespan before ``yield``, uvicorn would not accept connections (and
    ``/healthz`` would hang / connection-refused) until it finished. We simulate
    a slow rebuild and assert ``/healthz`` responds immediately while the build
    is still running in the background.
    """
    import sys
    import threading
    import time

    # NB: ``import rca_agent.webhook.app as X`` can bind to the FastAPI ``app``
    # attribute rather than the module; fetch the module explicitly.
    appmod = sys.modules["rca_agent.webhook.app"]
    assert hasattr(appmod, "_graph_builder"), "expected the module, not the app object"

    started = threading.Event()
    done = threading.Event()
    original = appmod._graph_builder.rebuild

    def slow_rebuild():
        started.set()
        time.sleep(1.5)
        done.set()
        return original()

    monkeypatch.setattr(appmod._graph_builder, "rebuild", slow_rebuild)

    t0 = time.time()
    with TestClient(appmod.app) as local_client:  # triggers lifespan startup
        latency = time.time() - t0
        r = local_client.get("/healthz")
        assert r.status_code == 200
        assert latency < 1.0, f"startup blocked on the graph build ({latency:.2f}s)"
        assert started.is_set(), "background build should have started"
        assert not done.is_set(), "build should still be running (non-blocking)"
