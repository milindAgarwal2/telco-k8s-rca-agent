"""Shared state passed between reasoning steps (LangGraph-compatible dict)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from rca_agent.models.alert import Alert
from rca_agent.models.incident import Evidence, Hypothesis


@dataclass
class ReasoningState:
    """Mutable working memory for one incident, threaded through the flow."""

    alert: Alert
    namespace: str
    affected_resource: str | None = None
    # Service-anchored model (0.7.0). Resolved in graph_walk from the graph.
    anchor_id: str | None = None
    anchor_kind: str | None = None
    anchor_display: str | None = None
    affected_pods: list[str] = field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None

    evidence: list[Evidence] = field(default_factory=list)
    unhealthy_upstream: list[str] = field(default_factory=list)
    blast_radius: list[str] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    suggested_next_steps: list[str] = field(default_factory=list)

    def add_evidence(self, ev: Evidence) -> None:
        self.evidence.append(ev)
