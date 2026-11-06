"""Shared pytest fixtures for DB-backed tests (durable PostgreSQL datastore).

The incident-persistence feature stores incidents and the runbook query log in a
separate PostgreSQL pod (``db-pg``). DB-backed tests must stay optional: a
contributor without PostgreSQL (and without the ``psycopg`` driver installed)
should still be able to run the rest of the suite. This module provides a
reusable skip-if-no-DB mechanism shared by every DB-backed test (Task 2.2 and
later tasks 3.2, 4.2, 8, 9).

Design choices:

* The DSN is read from a dedicated ``RCA_TEST_DATABASE_URL`` env var (falling
  back to ``RCA_DATABASE_URL``) so a production connection string is not reused
  by accident when only the prod var happens to be set.
* The ``psycopg`` / ``psycopg_pool`` import is guarded so importing this module
  (which pytest does at collection time) never errors in an environment without
  the driver -- the ``pg_database`` fixture simply skips instead.
"""
from __future__ import annotations

import os

import pytest

# Guarded import: psycopg is a core dependency in deployment (D2) but may be
# absent in a contributor's local/dev environment. Importing this conftest must
# not fail collection for the whole suite, so we detect availability here and
# let the fixture translate absence into a clean skip.
try:  # pragma: no cover - availability depends on the environment
    import psycopg  # noqa: F401
    import psycopg_pool  # noqa: F401

    _PSYCOPG_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means "no driver"
    _PSYCOPG_AVAILABLE = False

# Dedicated test DSN first so prod config is not reused accidentally.
# Mandatory-DB (D1) fail-fast: the app's lifespan calls get_store(), which
# raises ConfigurationError when RCA_DATABASE_URL is unset. Tests that boot the
# app via TestClient(app) (e.g. test_webhook.py) must therefore have SOME URL
# set so startup proceeds; the connect step is non-fatal (Req 5.1), so an
# unreachable dummy URL lets the app boot with /readyz simply reporting
# not-ready. We set a dummy ONLY when nothing is configured, so a real
# RCA_DATABASE_URL / RCA_TEST_DATABASE_URL is never overridden. DB-BACKED tests
# use the pg_database fixture below, which keys off RCA_TEST_DATABASE_URL, not
# this dummy.
# Keep the startup DB-connect backoff tiny for the whole test session so
# app-boot tests (TestClient(app)) do not burn the production retry budget
# against an unreachable DB. setdefault lets a developer running against a real
# DB override these.
os.environ.setdefault("RCA_DB_CONNECT_ATTEMPTS", "1")
os.environ.setdefault("RCA_DB_CONNECT_MAX_DELAY", "0")
os.environ.setdefault("RCA_DB_CONNECT_TIMEOUT", "1")
if not os.environ.get("RCA_DATABASE_URL") and not os.environ.get("RCA_TEST_DATABASE_URL"):
    os.environ["RCA_DATABASE_URL"] = "postgresql://rca:rca@127.0.0.1:5432/rca_test_unreachable"
_TEST_DSN_ENV = "RCA_TEST_DATABASE_URL"
_FALLBACK_DSN_ENV = "RCA_DATABASE_URL"


def _test_database_dsn() -> str | None:
    """Return the DSN for DB-backed tests, or ``None`` when none is configured.

    Prefers ``RCA_TEST_DATABASE_URL`` (a dedicated test database) and falls back
    to ``RCA_DATABASE_URL`` only if the test-specific var is unset.
    """
    return os.environ.get(_TEST_DSN_ENV) or os.environ.get(_FALLBACK_DSN_ENV)


@pytest.fixture
def pg_database():
    """Yield a connected :class:`Database` for DB-backed tests, else skip.

    Skips cleanly (rather than erroring) when:

    * no test DSN is configured (neither ``RCA_TEST_DATABASE_URL`` nor
      ``RCA_DATABASE_URL`` is set), or
    * the ``psycopg`` / ``psycopg_pool`` driver is not importable, or
    * the configured database is not reachable (``connect_with_retry`` with a
      single attempt leaves the pool not-ready).

    Otherwise it constructs a :class:`Database`, connects, yields the live
    instance, and closes the pool in teardown.
    """
    dsn = _test_database_dsn()
    if not dsn:
        pytest.skip("no test PostgreSQL configured")
    if not _PSYCOPG_AVAILABLE:
        pytest.skip("no test PostgreSQL configured")

    # Imported here (not at module top) so collection never depends on the
    # store package import succeeding in a driver-less environment.
    from rca_agent.store.db import Database

    database = Database(dsn)
    database.connect_with_retry(attempts=1)
    if not database.is_ready():
        database.close()
        pytest.skip("no test PostgreSQL configured")

    try:
        yield database
    finally:
        database.close()
