"""Queryable index over the service-area mapping."""
from __future__ import annotations

import logging
from pathlib import Path

from rca_agent.impact.loader import load_workbook_impacts, pod_stem
from rca_agent.impact.models import ServiceArea, ServiceAreaImpact

logger = logging.getLogger(__name__)


class ServiceAreaIndex:
    """Maps a pod name (exact or stem) to its ServiceAreaImpact."""

    def __init__(self, impacts: list[ServiceAreaImpact], areas: list[ServiceArea]) -> None:
        self._impacts = impacts
        self._areas = areas
        self._by_exact: dict[str, ServiceAreaImpact] = {}
        self._by_stem: dict[str, ServiceAreaImpact] = {}
        for imp in impacts:
            self._by_exact[imp.pod] = imp
            self._by_stem.setdefault(pod_stem(imp.pod), imp)

    def by_pod(self, pod_name: str) -> ServiceAreaImpact:
        """Resolve a pod to its impact. Tries exact name, then hash-stripped
        stem. Returns an UNKNOWN (unmapped) record if not found -- never raises,
        never guesses a service area."""
        if not pod_name:
            return ServiceAreaImpact(pod=pod_name or "")
        if pod_name in self._by_exact:
            return self._by_exact[pod_name]
        hit = self._by_stem.get(pod_stem(pod_name))
        if hit is not None:
            # Return a copy carrying the queried pod name for clarity.
            return hit.model_copy(update={"pod": pod_name})
        return ServiceAreaImpact(pod=pod_name)

    def all(self) -> list[ServiceAreaImpact]:
        return list(self._impacts)

    def areas(self) -> list[ServiceArea]:
        return list(self._areas)

    def __len__(self) -> int:
        return len(self._impacts)


def load_service_area_index(path: str | None) -> ServiceAreaIndex | None:
    """Load the index from a workbook path. Returns None when the feature is
    not configured (path falsy) or the file is missing/unreadable, so callers
    can treat 'no map' as 'feature off' (mirrors the runbook local_store)."""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        logger.info("service-area map not found at %s; feature inert", path)
        return None
    try:
        impacts, areas = load_workbook_impacts(str(p))
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to load service-area map %s: %s", path, exc)
        return None
    logger.info("service-area index loaded: %d pods, %d areas", len(impacts), len(areas))
    return ServiceAreaIndex(impacts, areas)
