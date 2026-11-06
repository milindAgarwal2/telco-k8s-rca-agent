"""Queryable index over the curated pod-alarm mapping.

Mirrors ``impact/index.py``: a pod name (exact or hash-stripped stem) resolves
to its ``PotentialAlarms`` record of CANDIDATE alarms. Unmapped pods return an
UNKNOWN record (``mapped=False``) -- never a guess, never a raise. The loader
returns ``None`` when the feature is not configured or the workbook cannot be
read, so callers treat 'no map' as 'feature off'.
"""
from __future__ import annotations

import logging
from pathlib import Path

from rca_agent.alarms.loader import load_workbook_alarms
from rca_agent.alarms.models import PotentialAlarms
from rca_agent.impact.loader import pod_stem  # single source of truth for the pod-name stem

logger = logging.getLogger(__name__)


class PotentialAlarmsIndex:
    """Maps a pod name (exact or stem) to its PotentialAlarms record."""

    def __init__(self, items: list[PotentialAlarms]) -> None:
        self._items = items
        self._by_exact: dict[str, PotentialAlarms] = {}
        self._by_stem: dict[str, PotentialAlarms] = {}
        for item in items:
            self._by_exact[item.pod] = item
            self._by_stem.setdefault(pod_stem(item.pod), item)

    def by_pod(self, pod_name: str) -> PotentialAlarms:
        """Resolve a pod to its candidate alarms. Tries exact name, then
        hash-stripped stem. Returns an UNKNOWN (unmapped) record if not found --
        never raises, never guesses an alarm."""
        if not pod_name:
            return PotentialAlarms(pod=pod_name or "", mapped=False, alarms=[])
        if pod_name in self._by_exact:
            return self._by_exact[pod_name]
        hit = self._by_stem.get(pod_stem(pod_name))
        if hit is not None:
            # Return a copy carrying the queried pod name for clarity.
            return hit.model_copy(update={"pod": pod_name})
        return PotentialAlarms(pod=pod_name, mapped=False, alarms=[])

    def all(self) -> list[PotentialAlarms]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


def load_potential_alarms_index(path: str | None) -> PotentialAlarmsIndex | None:
    """Load the index from a workbook path. Returns None when the feature is
    not configured (path falsy) or the file is missing/unreadable, so callers
    can treat 'no map' as 'feature off' (mirrors load_service_area_index)."""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        logger.info("pod-alarm map not found at %s; feature inert", path)
        return None
    try:
        items = load_workbook_alarms(str(p))
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to load pod-alarm map %s: %s", path, exc)
        return None
    logger.info("potential-alarms index loaded: %d pods", len(items))
    return PotentialAlarmsIndex(items)
