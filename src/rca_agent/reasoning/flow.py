"""LangGraph reasoning flow.

Wires the same deterministic steps as graph nodes, then adds an LLM re-rank /
explain node at the end. If LangGraph (the ``[llm]`` extra) is not installed, or
reasoning_mode != "llm", we transparently fall back to the extractive pipeline
so the service always works.

The LLM is constrained to RANK and EXPLAIN the rule-gathered hypotheses; it is
never given a tool to query the cluster and cannot introduce a cause that lacks
supporting evidence.
"""
from __future__ import annotations

from rca_agent.config import Settings, get_settings
from rca_agent.graph.dependency_graph import DependencyGraph
from rca_agent.models.alert import Alert
from rca_agent.models.incident import IncidentReport
from rca_agent.reasoning.extractive import ExtractivePipeline


def _langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
        return True
    except ImportError:
        return False


class ReasoningFlow:
    """Entry point used by the webhook. Chooses LLM or extractive mode."""

    def __init__(self, settings: Settings | None = None,
                 graph: DependencyGraph | None = None,
                 builder=None) -> None:
        self.cfg = settings or get_settings()
        self._extractive = ExtractivePipeline(self.cfg, graph=graph, builder=builder)

    def run(self, alert: Alert) -> IncidentReport:
        report = self._extractive.run(alert)
        if self.cfg.reasoning_mode == "llm" and _langgraph_available():
            report = self._llm_rerank(report)
        return report

    def _llm_rerank(self, report: IncidentReport) -> IncidentReport:
        """Re-rank/explain the extractive hypotheses with an LLM.

        TODO (Phase 2): build a LangGraph StateGraph whose final node calls the
        configured LLM with the structured evidence (untrusted text fenced) and
        asks it to order the existing hypotheses and write the evidence chain in
        prose. Must reject any hypothesis not already present. For now this is a
        pass-through so behavior is identical to extractive mode.
        """
        report.reasoning_mode = "llm (rerank pending Phase 2)"
        return report


def build_langgraph_app(settings: Settings | None = None):
    """Construct the compiled LangGraph app (only when the extra is installed).

    Returns None when LangGraph is unavailable so callers can fall back. The
    ``settings`` argument is reserved for Phase 2 (LLM provider wiring).
    """
    if not _langgraph_available():
        return None  # noqa: RET501 — explicit sentinel; Phase 2 returns a compiled app
    # TODO (Phase 2): assemble StateGraph nodes using `settings`:
    #   triage -> gather -> graph_walk -> change_correlation
    #           -> hypothesize_rank -> llm_explain -> report
    return None  # noqa: RET501 — explicit sentinel; Phase 2 returns a compiled app
