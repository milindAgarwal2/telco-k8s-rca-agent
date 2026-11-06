"""Persistence layer for the agent's durable datastore.

A thin PostgreSQL store (D1-D6) that :class:`~rca_agent.detection.event_watcher.EventWatcher`
and :class:`~rca_agent.rag.query_log.QueryLog` delegate to. This subpackage
imports only ``psycopg`` / ``psycopg_pool``, the stdlib, and the agent models --
never cluster or heavy app modules.

Currently exported: :class:`Database` (connection pool + schema),
:class:`ConfigurationError`, :class:`IncidentStore`, :class:`QueryLogStore`,
and the process-wide :class:`Store` singleton accessor :func:`get_store`.
"""
from __future__ import annotations

from rca_agent.store.db import ConfigurationError, Database
from rca_agent.store.factory import Store, get_store
from rca_agent.store.incident_store import IncidentStore
from rca_agent.store.query_log_store import QueryLogStore

__all__ = [
    "ConfigurationError",
    "Database",
    "IncidentStore",
    "QueryLogStore",
    "Store",
    "get_store",
]
