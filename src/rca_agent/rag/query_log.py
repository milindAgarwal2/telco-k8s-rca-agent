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

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache


@dataclass
class QueryLogEntry:
    timestamp: str
    query: str
    retriever: str  # type(retriever).__name__, e.g. "LocalRunbookRetriever"
    hit_count: int
    hit_titles: list[str] = field(default_factory=list)


class QueryLog:
    """Thread-safe, bounded, in-memory log of runbook-retrieval attempts."""

    def __init__(self, max_entries: int = 1000) -> None:
        self._lock = threading.Lock()
        self._entries: deque[QueryLogEntry] = deque(maxlen=max_entries)

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
        return n


@lru_cache
def get_query_log(max_entries: int | None = None) -> QueryLog:
    """Process-wide singleton, mirroring ``config.get_settings()``."""
    from rca_agent.config import get_settings
    return QueryLog(max_entries or get_settings().runbook_query_log_max_entries)
