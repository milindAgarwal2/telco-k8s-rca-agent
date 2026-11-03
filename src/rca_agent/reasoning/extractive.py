"""Extractive (no-LLM) reasoning pipeline.

Runs the six deterministic steps in order and assembles an IncidentReport. This
is the default mode: fully reproducible, cheap, and hard to hallucinate. The
LangGraph/LLM flow reuses the same steps and only adds a re-rank/explain stage.
"""
from __future__ import annotations

from rca_agent.config import Settings, get_settings
from rca_agent.graph.builder import GraphBuilder
from rca_agent.graph.dependency_graph import DependencyGraph
from rca_agent.impact.index import load_service_area_index
from rca_agent.models.alert import Alert
from rca_agent.models.incident import IncidentReport, Severity
from rca_agent.rag.local_store import get_local_store
from rca_agent.rag.query_log import get_query_log
from rca_agent.rag.runbook_retriever import get_runbook_retriever
from rca_agent.reasoning import steps
from rca_agent.reasoning.state import ReasoningState
from rca_agent.tools.query_tools import get_query_tools


class ExtractivePipeline:
    """Deterministic detect->gather->reason->report pipeline."""

    def __init__(self, settings: Settings | None = None,
                 graph: DependencyGraph | None = None,
                 builder: GraphBuilder | None = None) -> None:
        self.cfg = settings or get_settings()
        # Reuse the graph builder's read-only kube client for the query tools so
        # config is loaded once. Build the graph first (that bootstraps the
        # client), then hand the same client to the query tools. If a prebuilt
        # graph is passed with no builder, the tools build their own client
        # lazily on first use.
        self._builder = builder or GraphBuilder(self.cfg)
        self.graph = graph or self._builder.rebuild()
        kube_client = getattr(self._builder, "_kube", None)
        self.tools = get_query_tools(
            self.cfg.cluster_enabled,
            kube_client=kube_client,
            prometheus_url=self.cfg.prometheus_url,
        )
        self.query_log = get_query_log(self.cfg.runbook_query_log_max_entries)

    def run(self, alert: Alert) -> IncidentReport:
        ns = alert.namespace or self.cfg.namespace
        state = ReasoningState(alert=alert, namespace=ns,
                               affected_resource=alert.target)

        steps.triage(state, self.cfg)
        steps.gather_evidence(state, self.tools, self.cfg)
        steps.graph_walk(state, self.graph)
        steps.change_correlation(state, self.tools, self.cfg, graph=self.graph)
        steps.hypothesize_and_rank(state)
        # Resolved fresh per incident (not cached on self) so a runbook
        # uploaded through the dashboard after startup takes effect on the
        # very next incident, instead of staying frozen at whatever the
        # retriever was at pipeline-construction time.
        #
        # Semantic RAG is EXTRACTIVE-FIRST: it is only used when the opt-in
        # flag is set AND the [rag-semantic] deps are present AND the LLM
        # sidecar is opted-in + reachable (probed here). Otherwise the factory
        # transparently falls back to the extractive TF-IDF retriever.
        sidecar_live = False
        if self.cfg.runbook_rag_semantic:
            from rca_agent.reasoning.llm_rerank import sidecar_available
            sidecar_live = sidecar_available(self.cfg)
        retriever = get_runbook_retriever(
            self.cfg.runbook_rag_url,
            local_store=get_local_store(self.cfg.runbook_store_path),
            semantic=self.cfg.runbook_rag_semantic,
            sidecar_available=sidecar_live,
            embed_model=self.cfg.runbook_rag_embed_model,
        )
        steps.build_next_steps(state, retriever, self.cfg.runbook_rag_top_k,
                               query_log=self.query_log,
                               synthesize_cfg=(self.cfg if (self.cfg.runbook_rag_semantic
                                                            and sidecar_live) else None))
        # Scoped service-area impact. Resolved fresh per incident (like the
        # runbook retriever) so a re-uploaded mapping takes effect next
        # incident. None when RCA_SERVICE_AREA_MAP_PATH is unset/missing.
        steps.build_service_area(
            state, load_service_area_index(self.cfg.service_area_map_path))

        return self._to_report(state)

    def _to_report(self, state: ReasoningState) -> IncidentReport:
        severity = Severity.critical if state.alert.labels.get("severity") == "critical" \
            else Severity.warning
        report = IncidentReport(
            symptom=f"{state.alert.name} on {state.affected_resource or 'unknown'}",
            affected_resource=state.affected_resource,
            affected_anchor=state.anchor_id,
            anchor_kind=state.anchor_kind,
            affected_pods=state.affected_pods,
            namespace=state.namespace,
            severity=severity,
            detected_at=state.alert.starts_at,
            hypotheses=state.hypotheses,
            blast_radius=state.blast_radius,
            upstream_unhealthy=state.unhealthy_upstream,
            evidence=state.evidence,
            suggested_next_steps=state.suggested_next_steps,
            service_area=state.service_area,
            reasoning_mode="extractive",
        )
        return report.ranked()
