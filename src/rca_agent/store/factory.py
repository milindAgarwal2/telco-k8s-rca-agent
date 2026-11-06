"""Process-wide store singleton.

Bundles the :class:`~rca_agent.store.db.Database` connection pool with the two
store classes (:class:`~rca_agent.store.incident_store.IncidentStore` and
:class:`~rca_agent.store.query_log_store.QueryLogStore`) behind a single cached
accessor, :func:`get_store`.

Kept separate from :mod:`rca_agent.store.db` to avoid an import cycle: ``db``
owns only the connection concern and imports nothing from the agent config,
while this module reaches into :func:`rca_agent.config.get_settings` for the
DSN. The ``@lru_cache`` makes :func:`get_store` a process singleton, mirroring
the style of :func:`rca_agent.config.get_settings` and
:func:`rca_agent.rag.query_log.get_query_log`.

:func:`get_store` only *constructs* the store graph. It deliberately does NOT
open the pool (``connect_with_retry``) or create the schema (``ensure_schema``):
connection lifecycle is the app lifespan's job (see the startup wiring task).
Constructing :class:`Database` with an unset ``RCA_DATABASE_URL`` raises
:class:`~rca_agent.store.db.ConfigurationError` -- the fail-fast per Req 4.3.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from rca_agent.store.db import Database
from rca_agent.store.incident_store import IncidentStore
from rca_agent.store.query_log_store import QueryLogStore


@dataclass
class Store:
    """Container bundling the datastore pool and its two store classes."""

    db: Database
    incidents: IncidentStore
    query_log: QueryLogStore


@lru_cache
def get_store() -> Store:
    """Return the process-wide :class:`Store` singleton (Req 4.1).

    Reads ``RCA_DATABASE_URL`` from :func:`rca_agent.config.get_settings`,
    constructs the :class:`Database` (which raises
    :class:`~rca_agent.store.db.ConfigurationError` when the URL is unset --
    the fail-fast per Req 4.3), then the :class:`IncidentStore` and
    :class:`QueryLogStore` over it.

    Construction only: the pool is opened and the schema ensured later by the
    app lifespan, not here. ``get_settings`` is imported lazily (mirroring
    :func:`rca_agent.rag.query_log.get_query_log`) so importing this module does
    not trigger a settings load at import time.
    """
    from rca_agent.config import get_settings

    db = Database(get_settings().database_url)
    return Store(
        db=db,
        incidents=IncidentStore(db),
        query_log=QueryLogStore(db),
    )
