"""Reasoning flow entry point.

Runs the deterministic extractive pipeline, then — when ``reasoning_mode == 'llm'``
— asks a LOCAL llama.cpp sidecar to re-rank and explain the rule-gathered
hypotheses. The LLM is constrained to REORDER + EXPLAIN existing, evidence-backed
hypotheses; it is never given a tool to query the cluster and cannot introduce a
cause that lacks supporting evidence (see reasoning/llm_rerank.py guardrails).
Any LLM error/unavailable sidecar falls back transparently to the extractive
order, so the service always works and extractive stays the reproducible default.
"""
from __future__ import annotations

from rca_agent.config import Settings, get_settings
from rca_agent.graph.dependency_graph import DependencyGraph
from rca_agent.models.alert import Alert
from rca_agent.models.incident import IncidentReport
from rca_agent.reasoning.extractive import ExtractivePipeline


class ReasoningFlow:
    """Entry point used by the webhook. Chooses LLM-rerank or extractive mode."""

    def __init__(self, settings: Settings | None = None,
                 graph: DependencyGraph | None = None,
                 builder=None) -> None:
        self.cfg = settings or get_settings()
        self._extractive = ExtractivePipeline(self.cfg, graph=graph, builder=builder)

    def run(self, alert: Alert) -> IncidentReport:
        report = self._extractive.run(alert)
        if self.cfg.reasoning_mode == "llm":
            report = self._llm_rerank(report)
        return report

    def _llm_rerank(self, report: IncidentReport) -> IncidentReport:
        """Re-rank/explain the extractive hypotheses via the local LLM sidecar.

        Delegates to ``reasoning.llm_rerank.llm_rerank``, which enforces the
        guardrails (reorder + explain only, reject unknown ids, fence untrusted
        evidence) and falls back to the extractive order on any failure.
        """
        from rca_agent.reasoning.llm_rerank import llm_rerank
        return llm_rerank(report, self.cfg)
