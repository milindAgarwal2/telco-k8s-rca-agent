"""Durable persistence for :class:`~rca_agent.rag.query_log.QueryLogEntry`.

One append-only row per runbook-retrieval attempt in the ``runbook_query_log``
table (schema owned by :mod:`rca_agent.store.db`). Query-worthy fields are
mirrored into typed columns (``ts``, ``query``, ``retriever``, ``hit_count``)
while the full entry -- including ``hit_titles`` (the response/hits) -- is stored
in the ``payload`` JSONB column via ``dataclasses.asdict(entry)``. The payload is
the source of truth for reload: :meth:`QueryLogStore.load_recent` reconstructs
each entry with ``QueryLogEntry(**payload)`` so every field round-trips faithfully
(Req 9.2).

The entry's ``timestamp`` is an ISO-8601 string; it is parsed with
``datetime.fromisoformat`` for the typed ``ts`` timestamptz column, while the raw
ISO string is preserved verbatim in the payload so the reloaded entry matches the
original. Writes go through :meth:`QueryLogStore.append` (a plain INSERT, since
entries are append-only, Req 9.1). :meth:`QueryLogStore.clear` performs a durable
``TRUNCATE`` (Req 9.5) and :meth:`QueryLogStore.stats` computes the
total/positive/negative counts via SQL, matching the shape of the in-memory
``QueryLog.stats()``. All queries use the pooled connection from
:meth:`rca_agent.store.db.Database.connection` and parameterized ``%s``
placeholders -- values are never string-formatted into SQL.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime

from psycopg.types.json import Json

from rca_agent.rag.query_log import QueryLogEntry
from rca_agent.store.db import Database

logger = logging.getLogger("rca_agent.store")


_APPEND_SQL = """
    INSERT INTO runbook_query_log (
        ts,
        query,
        retriever,
        hit_count,
        payload
    )
    VALUES (%s, %s, %s, %s, %s)
"""

_LOAD_RECENT_SQL = """
    SELECT payload FROM runbook_query_log
    ORDER BY ts DESC
    LIMIT %s
"""

_COUNT_SQL = "SELECT count(*) FROM runbook_query_log"

_COUNT_NEGATIVE_SQL = "SELECT count(*) FROM runbook_query_log WHERE hit_count = 0"

_TRUNCATE_SQL = "TRUNCATE runbook_query_log"


class QueryLogStore:
    """Read/write access to the durable ``runbook_query_log`` table.

    Constructed with a connected :class:`~rca_agent.store.db.Database`; all
    methods borrow a pooled connection via ``db.connection()`` and commit after
    writes.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, entry: QueryLogEntry) -> None:
        """Insert a new query-log row (append-only, Req 9.1).

        The full entry is stored in the ``payload`` JSONB column via
        ``dataclasses.asdict`` (preserving ``hit_titles`` and the raw ISO
        ``timestamp`` string for a faithful round-trip). The typed columns are a
        query-friendly subset; ``entry.timestamp`` (an ISO-8601 string) is parsed
        with ``datetime.fromisoformat`` for the typed ``ts`` timestamptz column.
        """
        payload = asdict(entry)
        params = (
            datetime.fromisoformat(entry.timestamp),
            entry.query,
            entry.retriever,
            entry.hit_count,
            Json(payload),
        )
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_APPEND_SQL, params)
            conn.commit()
        logger.debug("Appended runbook query-log entry (retriever=%s)", entry.retriever)

    def load_recent(self, limit: int = 1000) -> list[QueryLogEntry]:
        """Return the most recent query-log entries, newest first (Req 9.3).

        Reads the ``payload`` JSONB column and reconstructs each entry with
        ``QueryLogEntry(**payload)`` so the full record -- including
        ``hit_titles`` -- round-trips. Rows are ordered by ``ts DESC`` to match
        the in-memory ``QueryLog.list_entries`` (newest first).
        """
        with self._db.connection() as conn, conn.cursor() as cur:
            cur.execute(_LOAD_RECENT_SQL, (limit,))
            rows = cur.fetchall()
        return [QueryLogEntry(**row[0]) for row in rows]

    def clear(self) -> int:
        """Delete all query-log rows and return how many were removed (Req 9.5).

        The row count is read first, then the table is truncated and committed,
        so the return value mirrors the in-memory ``QueryLog.clear()`` which
        returns the number of cleared entries. The clear is durable -- the rows
        are not re-populated on the next restart.
        """
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_COUNT_SQL)
                row = cur.fetchone()
                removed = int(row[0]) if row is not None else 0
                cur.execute(_TRUNCATE_SQL)
            conn.commit()
        logger.info("Cleared runbook query log (%d rows removed).", removed)
        return removed

    def stats(self) -> dict:
        """Return ``{"total", "negative", "positive"}`` via SQL counts (Req 9.4).

        ``negative`` counts entries with zero hits (``hit_count = 0``), matching
        the in-memory ``QueryLog.stats()``; ``positive`` is the remainder.
        """
        with self._db.connection() as conn, conn.cursor() as cur:
            cur.execute(_COUNT_SQL)
            total_row = cur.fetchone()
            cur.execute(_COUNT_NEGATIVE_SQL)
            negative_row = cur.fetchone()
        total = int(total_row[0]) if total_row is not None else 0
        negative = int(negative_row[0]) if negative_row is not None else 0
        return {"total": total, "negative": negative, "positive": total - negative}
