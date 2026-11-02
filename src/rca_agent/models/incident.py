"""Output schema: the incident report with ranked root-cause hypotheses."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from rca_agent.impact.models import ServiceAreaImpact


class Severity(str, Enum):
    critical = "critical"
    warning = "warning"
    info = "info"


class Citation(BaseModel):
    """A pointer to the primary evidence behind a claim."""

    kind: str  # "log" | "event" | "metric" | "runbook" | "graph" | "change"
    source: str  # pod name, PromQL query, runbook page, etc.
    detail: str = ""
    timestamp: datetime | None = None
    # For change citations: who made the edit and whether that actor is an
    # automation. Populated from Kubernetes managedFields (see
    # query_tools._change). None for non-change citations.
    actor: str | None = None          # raw managedFields manager, e.g. "helm"
    actor_source: str | None = None   # classified label, e.g. "human (kubectl)"
    is_automation: bool | None = None


class Evidence(BaseModel):
    """One structured piece of evidence gathered deterministically."""

    category: str  # "pod_status" | "event" | "log" | "metric" | "change" | "graph"
    summary: str
    resource: str | None = None
    timestamp: datetime | None = None
    citations: list[Citation] = Field(default_factory=list)


class Hypothesis(BaseModel):
    """A candidate root cause with a confidence score and an evidence chain."""

    cause: str
    # Human-readable chain, e.g.
    # "SMF errors <- UPF unreachable <- UPF OOMKilled <- memory limit lowered".
    evidence_chain: list[str] = Field(default_factory=list)
    confidence: float = 0.0  # 0.0 - 1.0
    supporting_evidence: list[Evidence] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class IncidentReport(BaseModel):
    """The agent's complete output for one detected fault."""

    incident_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Symptom: what fired, where, when.
    symptom: str
    affected_resource: str | None = None
    # Service-anchored model (0.7.0): the stable entity the fault is attributed
    # to (a Service, else owning workload, else the pod itself) and the pods
    # that are the evidence behind it. affected_resource stays = the anchor's
    # display (or the pod when pod-anchored) for backward compatibility.
    affected_anchor: str | None = None        # anchor node id
    anchor_kind: str | None = None            # "service" | "deployment" | "pod"
    affected_pods: list[str] = Field(default_factory=list)
    namespace: str | None = None
    severity: Severity = Severity.warning
    detected_at: datetime | None = None

    # Lifecycle (0.7.3): an incident is "active" while its affected pods are
    # still unhealthy, and flips to "inactive" (with resolved_at set) once the
    # fault clears. STRICT recovery: inactive only when ALL affected_pods are
    # healthy again in the current graph (see event_watcher.reconcile_status).
    status: str = "active"  # "active" | "inactive"
    resolved_at: datetime | None = None

    # Reasoning outputs.
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    blast_radius: list[str] = Field(default_factory=list)
    # Upstream dependencies currently unhealthy — the "possible causes" side of
    # the graph walk (downstream ``blast_radius`` is the impact side). Each is a
    # resource this one depends on (``calls`` edge) that is itself unhealthy.
    upstream_unhealthy: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    suggested_next_steps: list[str] = Field(default_factory=list)

    # Scoped service-area impact (0.9.0): which curated service AREA the
    # affected pod belongs to + factual redundancy counts. None when the
    # feature is off (no mapping configured) or the pod is unmapped. Additive
    # and defaulted so existing reports/serialization are unaffected. This is
    # IMPACT context (what area is affected), NOT a cause -- it never changes
    # hypothesis ranking.
    service_area: ServiceAreaImpact | None = None

    # Other incident_ids sharing this one's exact failure signature on a
    # DIFFERENT resource within the correlation window (see
    # ``detection/event_watcher.py::_correlate``). This is a deterministic
    # pattern flag, NOT a claimed root cause — the graph has no NF-to-NF
    # ``calls`` edges yet to name or verify a shared upstream dependency (see
    # PLAN.md Known Issues), so this never changes a hypothesis's confidence
    # or invents what the shared cause is. It exists so "12 pods failed
    # identically at once" shows up as one linked pattern instead of 12
    # unrelated-looking incidents.
    related_incidents: list[str] = Field(default_factory=list)

    # Provenance.
    reasoning_mode: str = "extractive"

    @property
    def top_hypothesis(self) -> Hypothesis | None:
        return self.hypotheses[0] if self.hypotheses else None

    def ranked(self) -> IncidentReport:
        """Return self with hypotheses sorted by confidence (desc)."""
        self.hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return self
