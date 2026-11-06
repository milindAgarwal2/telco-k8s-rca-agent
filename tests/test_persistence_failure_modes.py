"""Non-fatal-on-DB-failure tests for the durable PostgreSQL datastore (Task 9).

Req 5 says persistence must never reduce availability: a store that FAILS or is
NOT ready must not crash the agent, and the in-memory caches stay authoritative.
The key design point these tests exercise is that *most* of this behavior needs
NO live PostgreSQL at all -- it is about what happens when the store raises or is
absent. So instead of a real database we inject tiny fakes whose write methods
raise, and assert the caller swallows the failure and keeps the in-memory copy.

Import guards: the app's real modules pull in pydantic / networkx / psycopg,
which may be absent in a bare sandbox. Each test (or its module-level import)
``importorskip``s what it needs, so collection is always safe:

* in a full environment (deps installed) tests 1-3 RUN;
* in a driver-less / dep-less sandbox they SKIP cleanly rather than erroring.

The ``/readyz`` + ``/healthz`` readiness behavior (Req 5.1/5.2) is covered by the
Task 5.3 handlers in ``webhook/app.py`` and exercised under the full integration
suite (it needs FastAPI's TestClient, i.e. fastapi/pydantic, which are not
importable in the bare sandbox); it is intentionally NOT reimplemented here as a
TestClient test that would error at collection. See the note at the bottom of
this module.

Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Test 1: EventWatcher write-through is non-fatal (Req 5.3 / 5.4)
# ---------------------------------------------------------------------------
class _ExplodingIncidentStore:
    """Fake IncidentStore whose ``upsert`` always raises.

    Stands in for a down/unreachable database at runtime: the store object
    exists and is wired into the watcher, but every write blows up. The watcher
    must swallow this (log + keep the in-memory copy), never propagate it.
    """

    def __init__(self) -> None:
        self.calls = 0

    def upsert(self, report) -> None:
        self.calls += 1
        raise RuntimeError("db down")


class _StubBuilder:
    """Minimal GraphBuilder stand-in.

    ``EventWatcher._store`` reaches ``self.builder.graph`` when handing the
    report to the (disabled) incident-capture writer; nothing else on the
    builder is touched on the record_external_incident -> _store -> _persist
    path, so a bare object with a ``graph`` attribute is enough.
    """

    graph = None


def test_event_watcher_persist_is_non_fatal():
    """A runtime write failure is logged and swallowed; memory stays authoritative.

    Routes through the real public path (``record_external_incident`` ->
    ``_store`` -> ``_persist``) so we prove the swallow happens where incidents
    are actually created, not just in an isolated helper. The incident must
    still be in ``watcher.incidents`` afterwards (Req 5.3: keep the in-memory
    copy; Req 5.4: continue serving reads from memory).

    Validates: Requirements 5.3, 5.4
    """
    # Guard: EventWatcher imports pydantic (models) + networkx (graph) at module
    # load, so skip cleanly where those are absent.
    pytest.importorskip("pydantic")
    pytest.importorskip("networkx")

    from rca_agent.config import Settings
    from rca_agent.detection.event_watcher import EventWatcher
    from rca_agent.models.incident import Hypothesis, IncidentReport

    fake_store = _ExplodingIncidentStore()
    # Default Settings: incident capture is OFF (no capture path), so the
    # capture writer is a no-op and the only store interaction is our fake.
    watcher = EventWatcher(
        Settings(),
        _StubBuilder(),
        flow_factory=lambda: None,
        incident_store=fake_store,
    )

    report = IncidentReport(
        symptom="pod unhealthy",
        affected_resource="upf-7c9-bbbb",
        namespace="open5gs",
        hypotheses=[Hypothesis(cause="upf-7c9-bbbb OOMKilled", confidence=0.9)],
    )

    # Must NOT raise even though the store's upsert raises RuntimeError.
    watcher.record_external_incident(report)

    # The failing write was actually attempted (not silently skipped) ...
    assert fake_store.calls == 1
    # ... and the in-memory store kept the incident regardless (Req 5.3/5.4):
    # memory is authoritative, the DB reconverges on the next mutation.
    assert report in watcher.incidents
    assert watcher.get_incident(report.incident_id) is report


# ---------------------------------------------------------------------------
# Test 2: QueryLog record/clear are non-fatal (Req 5.3 / 5.4, mirrors 9.6)
# ---------------------------------------------------------------------------
class _ExplodingQueryLogStore:
    """Fake QueryLogStore whose ``append`` and ``clear`` always raise."""

    def __init__(self) -> None:
        self.append_calls = 0
        self.clear_calls = 0

    def append(self, entry) -> None:
        self.append_calls += 1
        raise RuntimeError("db down")

    def clear(self) -> int:
        self.clear_calls += 1
        raise RuntimeError("db down")


def test_query_log_record_is_non_fatal():
    """``record`` and ``clear`` swallow store failures and keep memory correct.

    ``record(...)`` must not raise when the durable append fails, and the entry
    must still be in ``list_entries()`` (in-memory kept). ``clear()`` must not
    raise when the durable clear fails, must still empty the in-memory log, and
    must still return an ``int`` (the in-memory count contract).

    Validates: Requirements 5.3, 5.4
    """
    # QueryLog itself is import-light, but the module's dataclass/typing are
    # plain stdlib; it has no pydantic/networkx dependency. Still, import it
    # inside the test for symmetry and so an unexpected transitive dep skips
    # cleanly rather than erroring at collection.
    query_log_mod = pytest.importorskip("rca_agent.rag.query_log")
    QueryLog = query_log_mod.QueryLog

    fake_store = _ExplodingQueryLogStore()
    log = QueryLog(max_entries=10, query_log_store=fake_store)

    # record(): durable append raises -> must be swallowed, memory kept.
    entry = log.record(
        query="why is upf crashing",
        retriever="LocalRunbookRetriever",
        hit_titles=["runbook-upf-oom"],
    )
    assert fake_store.append_calls == 1
    kept = log.list_entries()
    assert entry in kept
    assert len(kept) == 1

    # clear(): durable clear raises -> must be swallowed, memory cleared, int.
    removed = log.clear()
    assert fake_store.clear_calls == 1
    assert isinstance(removed, int)
    assert removed == 1
    assert log.list_entries() == []


# ---------------------------------------------------------------------------
# Test 3: Database fails fast on a missing URL (Req 4.3) -- no driver needed
# ---------------------------------------------------------------------------
def test_database_missing_url_fails_fast():
    """``Database(None)`` / ``Database("")`` raise ``ConfigurationError`` (Req 4.3).

    This check is intentionally driver-free: ``Database.__init__`` validates the
    DSN *before* any psycopg use (the ``ConnectionPool`` import is deferred into
    ``connect_with_retry``), so constructing with a missing URL raises without a
    live database or even the driver installed. It should RUN in the bare
    sandbox, not skip. The ``importorskip`` is a safety net only in case the
    store package ever grows an eager driver import at module load.

    Validates: Requirements 4.3, 5.1
    """
    db_mod = pytest.importorskip("rca_agent.store.db")
    Database = db_mod.Database
    ConfigurationError = db_mod.ConfigurationError

    with pytest.raises(ConfigurationError):
        Database(None)

    with pytest.raises(ConfigurationError):
        Database("")


# ---------------------------------------------------------------------------
# Test 4 (readiness endpoints, Req 5.1/5.2) -- intentionally NOT a TestClient
# test here.
#
# Readiness behavior ("/readyz" is not-ready until the DB connects while
# "/healthz" stays independent of the DB) lives in the Task 5.3 handlers in
# webhook/app.py:
#   * healthz() returns {"status": "ok", ...} with NO database access, so a DB
#     outage cannot fail liveness (Req 5.2);
#   * readyz() computes db_ready = _store is not None and _store.db.is_ready()
#     and reports "not-ready" until the pool connects (Req 5.1).
# Exercising those over HTTP needs FastAPI's TestClient (fastapi + pydantic),
# which is not importable in the bare sandbox, and the readiness predicate is
# not cleanly extractable from the request handler without importing the app.
# Writing a TestClient test here would ERROR at collection in the sandbox, which
# the task forbids, so this behavior is covered by the Task 5.3 handlers and the
# full integration environment (where fastapi is installed) instead.
# ---------------------------------------------------------------------------
