"""Tests for the PostgreSQL datastore connection layer (store/db.py).

These tests are DB-backed: they run only when a test PostgreSQL is configured
(see ``tests/conftest.py``'s ``pg_database`` fixture, which skips cleanly when no
test DSN is set or the ``psycopg`` driver is unavailable). Without a database
this module collects and skips rather than failing.
"""
from __future__ import annotations


def test_ensure_schema_idempotent(pg_database):
    """``ensure_schema()`` is safe to run repeatedly (Req 4.4).

    Calling it twice must not raise (the DDL is ``CREATE TABLE/INDEX IF NOT
    EXISTS``). After the second call both tables exist, confirmed via a catalog
    query.

    Validates: Requirements 4.4
    """
    # First call creates the schema; second call must be a no-op, not an error.
    pg_database.ensure_schema()
    pg_database.ensure_schema()

    # Confirm both tables exist in the current database's public catalog.
    with pg_database.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('incidents', 'runbook_query_log')
                ORDER BY table_name
                """
        )
        tables = {row[0] for row in cur.fetchall()}

    assert tables == {"incidents", "runbook_query_log"}
