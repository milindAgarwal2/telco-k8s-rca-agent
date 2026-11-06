"""DB-backed round-trip tests for the durable :class:`QueryLogStore`.

These tests exercise the append / load / stats / clear path against a real
PostgreSQL ``runbook_query_log`` table. They are DB-backed and therefore
OPTIONAL: they run only when a test PostgreSQL is configured (see
``tests/conftest.py``'s ``pg_database`` fixture, which skips cleanly when no test
DSN is set or the ``psycopg`` driver is unavailable). Without a database this
module collects and skips rather than failing.

Coverage:

* ``test_query_log_round_trip`` -- a positive entry (non-empty ``hit_titles``)
  and a negative entry (``hit_count`` 0, empty ``hit_titles``) survive
  ``append`` -> ``load_recent`` with every field intact, including
  ``hit_titles``, and are returned newest-first (Req 9.2).
* ``test_stats_matches_in_memory`` -- ``QueryLogStore.stats()`` equals the
  in-memory ``QueryLog.stats()`` for the same set of entries (Req 9.4).
* ``test_clear_empties_table`` -- ``clear()`` returns the number removed and
  leaves the table empty and durable (Req 9.5).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from rca_agent.rag.query_log import QueryLog, QueryLogEntry
from rca_agent.store.query_log_store import QueryLogStore

# Fixed timestamps keep the tests deterministic (no wall-clock drift) and give
# the entries a distinct, monotonically increasing order so newest-first
# ordering can be asserted. ``QueryLogEntry.timestamp`` is an ISO-8601 string,
# so we build them from ``datetime(...).isoformat()``.
_TS_OLDEST = datetime(2024, 1, 2, 3, 0, 0, tzinfo=timezone.utc).isoformat()
_TS_MIDDLE = datetime(2024, 1, 2, 3, 5, 0, tzinfo=timezone.utc).isoformat()
_TS_NEWEST = datetime(2024, 1, 2, 3, 10, 0, tzinfo=timezone.utc).isoformat()


def _clear_query_log(pg_database) -> None:
    """Empty the ``runbook_query_log`` table so each test starts clean."""
    QueryLogStore(pg_database).clear()


def _positive_entry() -> QueryLogEntry:
    """A matched retrieval attempt with a non-empty ``hit_titles`` list."""
    return QueryLogEntry(
        timestamp=_TS_OLDEST,
        query="UPF OOMKilled memory limit",
        retriever="LocalRunbookRetriever",
        hit_count=2,
        hit_titles=["UPF OOM runbook", "Memory tuning for UPF"],
    )


def _negative_entry() -> QueryLogEntry:
    """An unmatched retrieval attempt: zero hits, empty ``hit_titles``."""
    return QueryLogEntry(
        timestamp=_TS_NEWEST,
        query="SMF phantom error no runbook",
        retriever="LocalRunbookRetriever",
        hit_count=0,
        hit_titles=[],
    )


def test_query_log_round_trip(pg_database):
    """Entries survive ``append`` -> ``load_recent`` intact, newest first.

    A positive entry (non-empty ``hit_titles``) and a negative one
    (``hit_count`` 0, empty ``hit_titles``) are appended with distinct
    timestamps. ``load_recent`` must reconstruct both entries equal to the
    originals -- compared via ``dataclasses.asdict`` so ``hit_titles`` is
    included -- and return them newest-first (the negative entry, timestamped
    later, precedes the positive one).

    Validates: Requirements 9.2
    """
    pg_database.ensure_schema()
    _clear_query_log(pg_database)

    store = QueryLogStore(pg_database)
    positive = _positive_entry()  # _TS_OLDEST
    negative = _negative_entry()  # _TS_NEWEST
    store.append(positive)
    store.append(negative)

    reloaded = store.load_recent()

    # Full-field equivalence (including hit_titles) via asdict.
    assert [asdict(e) for e in reloaded] == [asdict(negative), asdict(positive)]
    # Newest-first ordering: the later-timestamped negative entry comes first.
    assert [e.timestamp for e in reloaded] == [_TS_NEWEST, _TS_OLDEST]
    # The positive entry's hit_titles round-tripped verbatim.
    assert reloaded[1].hit_titles == ["UPF OOM runbook", "Memory tuning for UPF"]


def test_stats_matches_in_memory(pg_database):
    """``QueryLogStore.stats()`` equals in-memory ``QueryLog.stats()``.

    The same set of entries (two positive, one negative) is appended to both a
    persistent ``QueryLogStore`` and an in-memory ``QueryLog``; the two
    ``stats()`` dicts (``total`` / ``positive`` / ``negative``) must match.

    Validates: Requirements 9.4
    """
    pg_database.ensure_schema()
    _clear_query_log(pg_database)

    entries = [
        _positive_entry(),
        QueryLogEntry(
            timestamp=_TS_MIDDLE,
            query="AMF restart loop",
            retriever="LocalRunbookRetriever",
            hit_count=1,
            hit_titles=["AMF restart runbook"],
        ),
        _negative_entry(),
    ]

    store = QueryLogStore(pg_database)
    memory = QueryLog()
    for entry in entries:
        store.append(entry)
        memory._entries.append(entry)

    expected = memory.stats()
    assert store.stats() == expected
    # Sanity: the shared shape has the expected counts (2 positive, 1 negative).
    assert expected == {"total": 3, "negative": 1, "positive": 2}


def test_clear_empties_table(pg_database):
    """``clear()`` returns the removed count and leaves the table empty.

    After appending entries, ``stats()["total"]`` is positive; ``clear()``
    returns the number removed; afterward ``stats()["total"]`` is zero and
    ``load_recent()`` is empty (the clear is durable, Req 9.5).

    Validates: Requirements 9.5
    """
    pg_database.ensure_schema()
    _clear_query_log(pg_database)

    store = QueryLogStore(pg_database)
    store.append(_positive_entry())
    store.append(_negative_entry())
    assert store.stats()["total"] > 0

    removed = store.clear()
    assert removed == 2

    assert store.stats()["total"] == 0
    assert store.load_recent() == []
