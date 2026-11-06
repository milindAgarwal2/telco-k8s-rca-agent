"""PostgreSQL datastore connection layer.

The agent's durable store (incidents + runbook query log) lives in a separate
PostgreSQL pod (``db-pg``). Per decision D1 this store is *mandatory*: the
connection string must be supplied via ``RCA_DATABASE_URL`` (sourced from a
Secret in deployment) and there is no in-memory-only runtime mode.

This module owns only the connection concern:

* :class:`Database` holds a small ``psycopg_pool.ConnectionPool`` and exposes
  :meth:`Database.connect_with_retry` (bounded exponential backoff at startup,
  Req 5.1), :meth:`Database.ensure_schema` (idempotent ``CREATE TABLE IF NOT
  EXISTS`` for both tables, Req 4.4), :meth:`Database.is_ready` (readiness flag
  consulted by ``/readyz``), and :meth:`Database.connection` (a pooled
  connection context manager used by the store classes).
* :class:`ConfigurationError` is raised when ``RCA_DATABASE_URL`` is unset so the
  agent fails fast at startup (Req 4.3) rather than silently running without
  durability.

The driver is ``psycopg`` v3 (synchronous) with ``psycopg_pool``, both core
dependencies (D2). Nothing here imports cluster or heavy app modules.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger("rca_agent.store")


class ConfigurationError(RuntimeError):
    """Raised when the datastore is misconfigured (e.g. ``RCA_DATABASE_URL`` unset).

    The PostgreSQL store is mandatory (D1); a missing connection string is a
    fatal configuration error surfaced at startup (Req 4.3) rather than a
    silent fallback to a non-durable mode.
    """


# --- Schema (D4: one table per store + a JSONB full-record column) ----------
# Idempotent DDL, safe to run on every startup (Req 4.4). Columns and indexes
# match design.md "Data Models".
_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS incidents (
        incident_id       text PRIMARY KEY,
        created_at        timestamptz NOT NULL,
        status            text NOT NULL,
        resolved_at       timestamptz NULL,
        affected_resource text NULL,
        namespace         text NULL,
        severity          text NULL,
        payload           jsonb NOT NULL,
        updated_at        timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS incidents_status_created_at_idx
        ON incidents (status, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS runbook_query_log (
        id        bigserial PRIMARY KEY,
        ts        timestamptz NOT NULL,
        query     text NOT NULL,
        retriever text NOT NULL,
        hit_count integer NOT NULL,
        payload   jsonb NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS runbook_query_log_ts_idx
        ON runbook_query_log (ts DESC)
    """,
)


class Database:
    """Owns the connection pool to the agent's PostgreSQL datastore.

    Construction is cheap and does **not** open any connection: the DSN is
    validated (fail fast if missing, Req 4.3) and the pool config is stored.
    The pool is opened lazily by :meth:`connect_with_retry`, so startup code can
    control retry/backoff and so an unreachable DB at construction time does not
    raise (the caller decides; readiness is reflected via :meth:`is_ready`).
    """

    def __init__(
        self,
        dsn: str | None,
        *,
        min_size: int = 1,
        max_size: int = 4,
    ) -> None:
        if not dsn:
            raise ConfigurationError(
                "RCA_DATABASE_URL is not set. The PostgreSQL datastore is "
                "mandatory (D1); set RCA_DATABASE_URL to the db-pg connection "
                "string (sourced from a Secret in deployment)."
            )
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        # Opened lazily by connect_with_retry(); None means "not connected".
        self._pool = None
        self._ready = False

    def connect_with_retry(
        self,
        attempts: int = 10,
        base_delay: float = 0.5,
        max_delay: float = 10.0,
        connect_timeout: float = 10.0,
    ) -> None:
        """Open the connection pool with bounded exponential backoff.

        Tries up to ``attempts`` times, sleeping ``min(max_delay, base_delay *
        2**n)`` between tries (Req 5.1). On success a ``SELECT 1`` confirms the
        pool is live and the readiness flag is set. On persistent failure the
        pool is left ``None`` and the readiness flag stays False; the method does
        **not** raise past the bounded attempts -- the caller decides what to do
        (at startup the lifespan treats not-ready as ``/readyz`` = false).
        """
        # Imported here (and lazily) so importing this module does not hard-fail
        # if the driver is somehow absent; psycopg is a core dependency (D2).
        from psycopg_pool import ConnectionPool

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                pool = ConnectionPool(
                    conninfo=self._dsn,
                    min_size=self._min_size,
                    max_size=self._max_size,
                    open=False,
                )
                # Bound the open so an unreachable DB fails THIS attempt fast
                # (the pool default is 300s, which would hang startup). On a down
                # DB this raises PoolTimeout quickly -> non-fatal, /readyz not-ready.
                pool.open(wait=True, timeout=connect_timeout)
                # Confirm the pool actually hands out a working connection.
                with pool.connection() as conn, conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                self._pool = pool
                self._ready = True
                logger.info(
                    "Connected to PostgreSQL datastore (pool min=%d max=%d) on attempt %d/%d",
                    self._min_size,
                    self._max_size,
                    attempt,
                    attempts,
                )
                return
            except Exception as exc:  # noqa: BLE001 - startup is non-fatal (Req 5.1)
                last_error = exc
                self._pool = None
                self._ready = False
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                logger.warning(
                    "PostgreSQL connect attempt %d/%d failed: %s; retrying in %.1fs",
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                if attempt < attempts:
                    time.sleep(delay)

        logger.error(
            "Could not connect to PostgreSQL datastore after %d attempts; "
            "store is not ready (/readyz will report not-ready). Last error: %s",
            attempts,
            last_error,
        )

    def is_ready(self) -> bool:
        """Return True only when a live pool is connected.

        Cheap: returns the cached readiness flag set by
        :meth:`connect_with_retry`. ``/readyz`` consults this; ``/healthz``
        (liveness) must NOT depend on the DB (Req 5.2).
        """
        return self._ready and self._pool is not None

    def ensure_schema(self) -> None:
        """Create the tables and indexes if they do not exist (idempotent).

        Runs the ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``
        statements for both ``incidents`` and ``runbook_query_log`` (design.md
        Data Models). Safe to call on every startup (Req 4.4). Requires a
        connected pool -- call :meth:`connect_with_retry` first.
        """
        if self._pool is None:
            raise ConfigurationError(
                "ensure_schema() called before a pool was connected; call "
                "connect_with_retry() first."
            )
        with self.connection() as conn:
            with conn.cursor() as cur:
                for statement in _SCHEMA_STATEMENTS:
                    cur.execute(statement)
            conn.commit()
        logger.info("Datastore schema ensured (incidents, runbook_query_log).")

    @contextmanager
    def connection(self) -> Iterator[object]:
        """Yield a pooled connection for the store classes to use.

        Usage (in :class:`IncidentStore` / :class:`QueryLogStore`, later tasks)::

            with db.connection() as conn:
                with conn.cursor() as cur:
                    ...
        """
        if self._pool is None:
            raise ConfigurationError(
                "No connection pool; call connect_with_retry() first."
            )
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        """Close the connection pool and mark the store not-ready."""
        pool = self._pool
        self._pool = None
        self._ready = False
        if pool is not None:
            try:
                pool.close()
                logger.info("Closed PostgreSQL datastore connection pool.")
            except Exception as exc:  # noqa: BLE001 - shutdown is best-effort
                logger.warning("Error closing PostgreSQL pool: %s", exc)
