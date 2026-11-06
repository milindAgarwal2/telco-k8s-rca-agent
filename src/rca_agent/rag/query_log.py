"""Runbook query log.

Records every runbook-retrieval attempt made via
``reasoning.steps.build_next_steps`` -- not LLM calls, since the extractive
pipeline has no LLM call anywhere -- so you can see what's being asked and
whether anything matched. A "negative" entry (zero hits) is the signal for
"write a runbook for this."

In-memory, like the incident list (``detection/event_watcher.py``) -- same
accepted limitation, wiped on redeploy until Postgres persistence (still on
the pending list) covers both. Bounded by ``runbook_query_log_max_entries``
(oldest entries dropped first via a ``deque(maxlen=...)``).
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # import-light: avoid a store<->rag import cycle at runtime.
    from rca_agent.store.query_log_store import QueryLogStore

logger = logging.getLogger("rca_agent.rag")


@dataclass
class QueryLogEntry:
    timestamp: str
    query: str
    retriever: str  # type(retriever).__name__, e.g. "LocalRunbookRetriever"
    hit_count: int
    hit_titles: list[str] = field(default_factory=list)


class QueryLog:
    """Thread-safe, bounded, in-memory log of runbook-retrieval attempts."""

    def __init__(self, max_entries: int = 1000,
                 query_log_store: QueryLogStore | None = None) -> None:
        self._lock = threading.Lock()
        self._entries: deque[QueryLogEntry] = deque(maxlen=max_entries)
        # Durable store for write-through (Req 9.1). Optional so the lru_cache
        # factory below (and tests/dev) construct a QueryLog without a DB; the
        # app injects the store after construction (see webhook/app.py
        # _startup_store), mirroring the EventWatcher._incident_store pattern.
        # When None, record()/clear() behave exactly as before.
        self._store = query_log_store

    def record(self, query: str, retriever: str, hit_titles: list[str]) -> QueryLogEntry:
        entry = QueryLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            query=query,
            retriever=retriever,
            hit_count=len(hit_titles),
            hit_titles=hit_titles,
        )
        with self._lock:
            self._entries.append(entry)
        # Write-through to the durable store OUTSIDE the lock: the entry is
        # already captured in-memory, so we must not hold self._lock during
        # blocking DB I/O (matches list_entries/stats, which copy under the
        # lock and work on the copy afterward). Non-fatal (Req 9.6): a write
        # failure is logged and swallowed, never raised, so a DB outage cannot
        # break runbook retrieval.
        if self._store is not None:
            try:
                self._store.append(entry)
            except Exception:
                logger.warning("query-log durable append failed (non-fatal); "
                               "keeping in-memory entry", exc_info=True)
        return entry

    def list_entries(self, limit: int | None = None) -> list[QueryLogEntry]:
        """Newest first."""
        with self._lock:
            entries = list(self._entries)
        entries.reverse()
        return entries[:limit] if limit else entries

    def stats(self) -> dict:
        with self._lock:
            entries = list(self._entries)
        total = len(entries)
        negative = sum(1 for e in entries if e.hit_count == 0)
        return {"total": total, "negative": negative, "positive": total - negative}

    def clear(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        # Also clear the durable rows (Req 9.5) OUTSIDE the lock, so the DB
        # clear is durable -- a cleared log stays cleared across restarts and
        # is not re-populated on the next rehydrate. Non-fatal: a failure is
        # logged and swallowed. The in-memory count is the return value to
        # preserve the existing contract (the DB count may differ once history
        # grows past the in-memory cap, Req 9.7).
        if self._store is not None:
            try:
                self._store.clear()
            except Exception:
                logger.warning("query-log durable clear failed (non-fatal); "
                               "in-memory log cleared", exc_info=True)
        return n

    def rehydrate(self, entries: list[QueryLogEntry]) -> None:
        """Fill the in-memory deque from persisted entries (Req 9.3).

        ``entries`` is expected newest-first (as returned by
        ``QueryLogStore.load_recent``); they are appended OLDEST-first so the
        bounded ``deque(maxlen=...)`` keeps the most-recent entries. Lets the
        app rehydrate without poking ``_entries`` directly.
        """
        with self._lock:
            for entry in reversed(entries):
                self._entries.append(entry)


@lru_cache
def get_query_log(max_entries: int | None = None) -> QueryLog:
    """Process-wide singleton, mirroring ``config.get_settings()``."""
    from rca_agent.config import get_settings
    return QueryLog(max_entries or get_settings().runbook_query_log_max_entries)
