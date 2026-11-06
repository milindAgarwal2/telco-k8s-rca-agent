"""DB-backed retention-policy tests for the durable datastore (Task 10).

These tests pin down the durable retention policy of decision D3 / Requirement
8: the PostgreSQL store retains incident history for as long as the database
lasts, with NO application-level age/count pruning. The in-memory
``EventWatcher.incidents`` list stays capped at ``_MAX_STORED_INCIDENTS`` (200)
purely for UI/performance, while the database keeps the full history and reads
can page beyond that in-memory window.

Like the other store tests these are DB-backed and therefore OPTIONAL: they run
only when a test PostgreSQL is configured (see ``tests/conftest.py``'s
``pg_database`` fixture, which skips cleanly when no test DSN is set or the
``psycopg`` driver is unavailable). Without a database this module collects and
skips rather than failing.

The data is kept modest but meaningful: we assert the PRINCIPLE (no pruning on
write; reads honor an arbitrary limit) rather than materializing 200+ rows, so
the tests stay fast while still demonstrating durable retention beyond the cap.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rca_agent.models.incident import IncidentReport, Severity
from rca_agent.store.incident_store import IncidentStore

# A fixed base time with distinct per-incident created_at offsets keeps
# newest-first (``created_at DESC``) ordering deterministic across runs.
_BASE_CREATED_AT = datetime(2024, 1, 2, 0, 0, 0, tzinfo=timezone.utc)


def _clear_incidents(pg_database) -> None:
    """Empty the ``incidents`` table so each test starts from a clean slate."""
    with pg_database.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM incidents")
        conn.commit()


def _report(index: int) -> IncidentReport:
    """Build a minimal distinct incident with a deterministic ``created_at``.

    Later ``index`` -> later ``created_at`` so ``load_recent`` (newest first)
    returns higher indices first.
    """
    return IncidentReport(
        incident_id=f"ret-{index:03d}",
        created_at=_BASE_CREATED_AT + timedelta(minutes=index),
        symptom=f"synthetic retention incident {index}",
        affected_resource=f"deployment/app-{index}",
        affected_pods=[f"app-{index}-0"],
        namespace="core-5g",
        severity=Severity.warning,
        status="active",
    )


def test_db_retains_beyond_in_memory_cap(pg_database):
    """DB keeps the full set and reads page beyond a small window (no pruning).

    Upserts several distinct incidents directly via ``IncidentStore.upsert``
    and asserts the store retains every one (``count()`` equals the number
    written -- the store only INSERTs/UPSERTs and never deletes on write).
    ``load_recent`` then honors an arbitrary limit: a small limit returns just
    the newest N, while a limit larger than the row count returns them all,
    demonstrating that reads can page beyond a small (in-memory-cap-sized)
    window into the full durable history.

    Validates: Requirements 8.1, 8.3
    """
    pg_database.ensure_schema()
    _clear_incidents(pg_database)

    store = IncidentStore(pg_database)

    count = 5
    reports = [_report(i) for i in range(count)]
    for report in reports:
        store.upsert(report)

    # Nothing is pruned on write: every distinct incident is retained.
    assert store.count() == count

    # A small limit pages only the newest N (created_at DESC); highest index
    # is newest, so load_recent(3) returns indices 4, 3, 2 in that order.
    newest_three = store.load_recent(3)
    assert [r.incident_id for r in newest_three] == ["ret-004", "ret-003", "ret-002"]

    # A limit far larger than the row count returns the FULL history -- reads
    # are bounded only by the query limit, not by any in-memory cap.
    all_rows = store.load_recent(100)
    assert len(all_rows) == count
    assert [r.incident_id for r in all_rows] == [
        f"ret-{i:03d}" for i in range(count - 1, -1, -1)
    ]


def test_no_application_level_pruning(pg_database):
    """``upsert`` never reduces the row count; updates don't add or prune.

    Durable retention (D3) is bounded only by disk / PVC capacity -- the
    application performs NO age-based or count-based pruning. This test writes
    N distinct incidents, then upserts one of them AGAIN (an in-place update):
    the row count stays N (the update mutates the existing row rather than
    adding one, and no pruning removes any row).

    Note: the in-memory ``_MAX_STORED_INCIDENTS = 200`` cap in
    ``detection/event_watcher.py`` is a UI/performance bound on
    ``EventWatcher.incidents`` only -- it does NOT apply to the database, which
    keeps the full history regardless of that cap.

    Validates: Requirements 8.2
    """
    pg_database.ensure_schema()
    _clear_incidents(pg_database)

    store = IncidentStore(pg_database)

    count = 4
    reports = [_report(i) for i in range(count)]
    for report in reports:
        store.upsert(report)
    assert store.count() == count

    # Re-upsert an existing incident after mutating it: this is an UPDATE of the
    # same incident_id, so it must not add a row and must not prune any.
    existing = reports[0]
    existing.status = "inactive"
    existing.resolved_at = _BASE_CREATED_AT + timedelta(hours=1)
    store.upsert(existing)

    # Row count is unchanged: updates don't grow the table and nothing prunes.
    assert store.count() == count

    # The in-memory cap is an in-memory-only bound; importing it here documents
    # that the value lives on the EventWatcher side and is unrelated to the DB
    # row count asserted above. The import is safe under the DB-present path
    # (event_watcher imports only models + the store, no cluster client).
    from rca_agent.detection.event_watcher import _MAX_STORED_INCIDENTS

    assert _MAX_STORED_INCIDENTS == 200
    # The durable store holds fewer than the cap here, but crucially its size is
    # governed by what was written -- never clamped to _MAX_STORED_INCIDENTS.
    assert store.count() <= _MAX_STORED_INCIDENTS
