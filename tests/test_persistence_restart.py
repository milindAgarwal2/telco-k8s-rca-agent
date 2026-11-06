"""Restart-survival and read-path integration tests (component-level).

These tests prove the durable datastore fixes the confirmed production defect:
a clean agent restart wiped the in-memory incident list and runbook query log
(``GET /incidents?status=all`` returned ``count:0`` afterward). They exercise
the full ``persist -> simulate restart -> rehydrate -> read`` path against a real
PostgreSQL ``incidents`` / ``runbook_query_log`` table.

They are DB-backed and therefore OPTIONAL: they run only when a test PostgreSQL
is configured (see ``tests/conftest.py``'s ``pg_database`` fixture, which skips
cleanly when no test DSN is set or the ``psycopg`` driver is unavailable).
Without a database this module collects and skips rather than failing.

Why simulate the restart at the component level: wiring the full FastAPI app
with a live DB at import time is awkward in this sandbox. Instead each test
drives the exact store methods the production lifespan and endpoints use --
``IncidentStore.upsert`` / ``load_recent`` / ``get`` and ``QueryLogStore`` via
``QueryLog`` -- and replicates the two pieces of app logic verbatim:

* ``webhook/app.py`` ``_startup_store`` rehydration:
  ``_event_watcher.incidents[:] = list(reversed(load_recent(200)))`` and
  ``_query_log.rehydrate(load_recent(max_entries))``;
* ``webhook/app.py`` ``list_incidents`` filter:
  ``[r for r in reversed(incidents) if r.status == status]``.

This is faithful to the production failure and to the lifespan logic without
standing up uvicorn or a cluster.

Coverage:

* ``test_inactive_incident_survives_restart`` -- an incident flipped to
  ``inactive`` before a restart is still returned by the ``status=inactive``
  filter after rehydration (the exact scenario that returned ``count:0`` in
  production); the ``active`` filter still returns the active one (Req 3.2, 3.3).
* ``test_query_log_survives_restart_and_durable_clear`` -- recorded query-log
  entries survive a simulated restart via rehydration, and a durable
  ``clear()`` stays cleared across a subsequent restart (Req 9.3, 9.5).
* ``test_read_contract_shape_is_stable`` -- an incident's serialized shape is
  identical whether read as the freshly-created object or reloaded from the DB
  via ``get`` and ``load_recent`` (Req 7.1, 7.3).
"""
from __future__ import annotations

from datetime import datetime, timezone

from rca_agent.impact.models import ServiceAreaImpact
from rca_agent.models.incident import (
    Citation,
    Evidence,
    Hypothesis,
    IncidentReport,
    Severity,
)
from rca_agent.rag.query_log import QueryLog
from rca_agent.store.incident_store import IncidentStore
from rca_agent.store.query_log_store import QueryLogStore

# Fixed timestamps keep the tests deterministic (no wall-clock drift between the
# constructed models and the reloaded ones, and a stable newest-first order).
_CREATED_ACTIVE = datetime(2024, 1, 2, 3, 0, 0, tzinfo=timezone.utc)
_CREATED_INACTIVE = datetime(2024, 1, 2, 3, 5, 0, tzinfo=timezone.utc)
_RESOLVED_AT = datetime(2024, 1, 2, 3, 30, 0, tzinfo=timezone.utc)
_DETECTED_AT = datetime(2024, 1, 2, 2, 59, 0, tzinfo=timezone.utc)
_CITATION_TS = datetime(2024, 1, 2, 2, 58, 0, tzinfo=timezone.utc)

_TS_OLDEST = datetime(2024, 1, 2, 3, 0, 0, tzinfo=timezone.utc).isoformat()
_TS_NEWEST = datetime(2024, 1, 2, 3, 10, 0, tzinfo=timezone.utc).isoformat()


def _clear_tables(pg_database) -> None:
    """Empty BOTH tables so each test starts from a clean slate (independence).

    Uses a direct ``DELETE`` on ``incidents`` and ``QueryLogStore.clear()``
    (a durable ``TRUNCATE``) on ``runbook_query_log`` -- the same clearing
    approach the existing store tests use.
    """
    with pg_database.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM incidents")
        conn.commit()
    QueryLogStore(pg_database).clear()


def _rehydrate_incidents(store: IncidentStore) -> list[IncidentReport]:
    """Replicate ``_startup_store`` rehydration into a FRESH in-memory list.

    Mirrors ``webhook/app.py`` ``_startup_store``:
    ``_event_watcher.incidents[:] = list(reversed(store.load_recent(200)))``.
    """
    fresh: list[IncidentReport] = []
    fresh[:] = list(reversed(store.load_recent(200)))
    return fresh


def _filter_incidents(incidents: list[IncidentReport], status: str) -> list[IncidentReport]:
    """Replicate the ``/incidents?status=...`` filter from ``list_incidents``.

    Mirrors ``webhook/app.py`` ``list_incidents``: newest-first is
    ``reversed(_event_watcher.incidents)``, then filter by status unless "all".
    """
    newest_first = list(reversed(incidents))
    if status == "all":
        return newest_first
    return [r for r in newest_first if r.status == status]


def _active_report() -> IncidentReport:
    """An incident that stays active across the restart."""
    return IncidentReport(
        incident_id="restart-active",
        created_at=_CREATED_ACTIVE,
        symptom="AMF latency elevated",
        affected_resource="deployment/amf",
        affected_pods=["amf-0"],
        namespace="core-5g",
        severity=Severity.warning,
        status="active",
    )


def _inactive_report() -> IncidentReport:
    """An incident created active, then flipped to inactive before the restart."""
    return IncidentReport(
        incident_id="restart-inactive",
        created_at=_CREATED_INACTIVE,
        symptom="UPF OOMKilled",
        affected_resource="deployment/upf",
        affected_pods=["upf-0"],
        namespace="core-5g",
        severity=Severity.critical,
        status="active",
    )


def _rich_report() -> IncidentReport:
    """A fully populated report touching every nested structure (for 8.3)."""
    citation = Citation(
        kind="change",
        source="deployment/upf",
        detail="memory limit lowered 512Mi -> 128Mi",
        timestamp=_CITATION_TS,
        actor="kubectl",
        actor_source="human (kubectl)",
        is_automation=False,
    )
    supporting = Evidence(
        category="change",
        summary="UPF memory limit was lowered shortly before the incident",
        resource="deployment/upf",
        timestamp=_CITATION_TS,
        citations=[citation],
    )
    hypothesis = Hypothesis(
        cause="UPF OOMKilled after memory limit lowered",
        evidence_chain=["SMF errors", "UPF unreachable", "UPF OOMKilled"],
        confidence=0.82,
        supporting_evidence=[supporting],
        citations=[citation],
    )
    service_area = ServiceAreaImpact(
        pod="upf-0",
        mapped=True,
        component="PC VPN Gateway Forwarder",
        service_area="VPN Gateway",
        section="18",
        relationship_type="Direct component match",
        confidence="High",
        component_sibling_count=3,
        service_area_pod_count=7,
    )
    return IncidentReport(
        incident_id="restart-shape",
        created_at=_CREATED_INACTIVE,
        symptom="SMF reporting elevated 5xx to UPF",
        affected_resource="deployment/upf",
        affected_anchor="service/upf",
        anchor_kind="service",
        affected_pods=["upf-0", "upf-1"],
        namespace="core-5g",
        severity=Severity.critical,
        detected_at=_DETECTED_AT,
        status="inactive",
        resolved_at=_RESOLVED_AT,
        hypotheses=[hypothesis],
        blast_radius=["service/smf", "service/amf"],
        upstream_unhealthy=["deployment/upf"],
        evidence=[supporting],
        suggested_next_steps=["Raise the UPF memory limit back to 512Mi"],
        service_area=service_area,
        related_incidents=["restart-sibling-1", "restart-sibling-2"],
        reasoning_mode="extractive",
    )


def test_inactive_incident_survives_restart(pg_database):
    """An inactive incident is still returned by the status filter post-restart.

    This is the exact production failure: a clean restart wiped the in-memory
    store and ``/incidents?status=inactive`` returned nothing. We persist two
    incidents (one that stays active, one flipped to inactive -- mimicking
    ``reconcile_status`` setting ``status="inactive"`` + ``resolved_at`` and
    re-``upsert``-ing write-through), then simulate the restart by rehydrating a
    FRESH in-memory list from ``load_recent`` (exactly what ``_startup_store``
    does) and replicating the ``list_incidents`` status filter. The
    previously-inactive incident must appear under ``status=inactive`` and the
    active one under ``status=active``.

    Validates: Requirements 3.2, 3.3
    """
    pg_database.ensure_schema()
    _clear_tables(pg_database)

    incidents = IncidentStore(pg_database)

    # --- Before restart: create both incidents, then flip one to inactive. ---
    active = _active_report()
    going_inactive = _inactive_report()
    incidents.upsert(active)
    incidents.upsert(going_inactive)

    # Mimic reconcile_status: flip to inactive + set resolved_at, re-persist.
    going_inactive.status = "inactive"
    going_inactive.resolved_at = _RESOLVED_AT
    incidents.upsert(going_inactive)

    # --- After restart: rehydrate a FRESH in-memory list from the DB. ---
    fresh = _rehydrate_incidents(incidents)

    # The inactive filter returns the previously-inactive incident (the exact
    # scenario that returned count:0 in production).
    inactive = _filter_incidents(fresh, "inactive")
    assert [r.incident_id for r in inactive] == ["restart-inactive"]
    assert inactive[0].status == "inactive"
    assert inactive[0].resolved_at == _RESOLVED_AT

    # The active filter returns the still-active incident.
    still_active = _filter_incidents(fresh, "active")
    assert [r.incident_id for r in still_active] == ["restart-active"]

    # status=all returns both, newest-first (inactive was created later).
    everything = _filter_incidents(fresh, "all")
    assert [r.incident_id for r in everything] == ["restart-inactive", "restart-active"]


def test_query_log_survives_restart_and_durable_clear(pg_database):
    """Query-log entries survive a restart; a durable clear stays cleared.

    Record a couple of entries through a ``QueryLog`` wired to a
    ``QueryLogStore`` (verifying they persist), then simulate a restart with a
    fresh ``QueryLog`` rehydrated from ``load_recent`` -- the entries must come
    back (Req 9.3). Then ``clear()`` (durable, Req 9.5) and simulate ANOTHER
    restart: the rehydrated fresh log must be empty because the clear removed
    the rows and they are not re-populated.

    Validates: Requirements 9.3, 9.5
    """
    pg_database.ensure_schema()
    _clear_tables(pg_database)

    qstore = QueryLogStore(pg_database)
    writer = QueryLog(max_entries=1000, query_log_store=qstore)

    positive = writer.record(
        query="UPF OOMKilled memory limit",
        retriever="LocalRunbookRetriever",
        hit_titles=["UPF OOM runbook", "Memory tuning for UPF"],
    )
    negative = writer.record(
        query="SMF phantom error no runbook",
        retriever="LocalRunbookRetriever",
        hit_titles=[],
    )

    # The write-through persisted both entries.
    assert qstore.stats()["total"] == 2

    # --- First simulated restart: fresh QueryLog + rehydrate from the DB. ---
    reloaded = QueryLog(max_entries=1000, query_log_store=qstore)
    reloaded.rehydrate(qstore.load_recent(1000))

    survived = reloaded.list_entries()  # newest first
    # Both entries survived; the later-recorded negative entry comes first.
    assert [e.query for e in survived] == [negative.query, positive.query]
    assert survived[1].hit_titles == positive.hit_titles

    # --- Durable clear, then a SECOND restart: the log must stay empty. ---
    removed = reloaded.clear()
    assert removed == 2

    after_clear = QueryLog(max_entries=1000, query_log_store=qstore)
    after_clear.rehydrate(qstore.load_recent(1000))
    assert after_clear.list_entries() == []
    assert qstore.stats()["total"] == 0


def test_read_contract_shape_is_stable(pg_database):
    """A reloaded incident's serialized shape matches the freshly-created one.

    Upsert a richly populated incident, then read it back two ways the API uses
    -- ``get(incident_id)`` (``/incidents/{id}``) and ``load_recent(1)[0]``
    (the ``/incidents`` list) -- and assert both ``model_dump(mode="json")``
    equal the original object's. This demonstrates the read contract is
    shape-stable whether an incident is freshly created or reloaded from the DB.
    (Full ``/incidents`` endpoint wiring with a live app is out of scope for the
    sandbox; the store-level equality is the faithful, runnable proof.)

    Validates: Requirements 7.1, 7.3
    """
    pg_database.ensure_schema()
    _clear_tables(pg_database)

    store = IncidentStore(pg_database)
    original = _rich_report()
    expected = original.model_dump(mode="json")

    store.upsert(original)

    # /incidents/{id} path: get(incident_id).
    by_id = store.get(original.incident_id)
    assert by_id is not None
    assert by_id.model_dump(mode="json") == expected

    # /incidents list path: load_recent newest-first.
    recent = store.load_recent(1)
    assert len(recent) == 1
    assert recent[0].model_dump(mode="json") == expected
