"""Service-area impact: map an (unhealthy) pod to the service AREA it belongs to.

Scoped, high-confidence feature: it reports ONLY what the curated mapping
workbook supports directly -- the service area / component a pod belongs to, the
PDF section, the mapping confidence, and factual redundancy counts (how many
pods share the component, and how many pods the whole service area has). It does
NOT infer alerts, severity, downstream blast radius, or a full-vs-partial
outage verdict (those parts of the source data were low-confidence).

Read-only and deterministic: the mapping is curated data, never an LLM guess.
Every surfaced claim cites the workbook.
"""
from rca_agent.impact.index import ServiceAreaIndex, load_service_area_index
from rca_agent.impact.models import ServiceArea, ServiceAreaImpact

__all__ = [
    "ServiceArea",
    "ServiceAreaImpact",
    "ServiceAreaIndex",
    "load_service_area_index",
]
