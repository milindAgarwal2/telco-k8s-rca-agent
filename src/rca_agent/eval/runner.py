"""The harness runner: inject -> run the REAL pipeline -> score.

For each :class:`FaultCase` it builds a fake-kube cluster, hands it to a real
:class:`GraphBuilder`, runs the real :class:`ReasoningFlow` (extractive, no LLM,
no network), and scores the ranked hypotheses top-2 against the known cause.

Cluster-free and deterministic — safe to run in CI.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rca_agent.config import Settings
from rca_agent.eval.cases import FAULT_LIBRARY, FaultCase
from rca_agent.eval.fake_cluster import FakeKubeClient
from rca_agent.eval.scorer import Score, score_case
from rca_agent.graph.builder import GraphBuilder
from rca_agent.reasoning.flow import ReasoningFlow


@dataclass
class CaseResult:
    case_id: str
    fault_type: str
    description: str
    expected: str
    top_cause: str
    score: Score
    error: str | None = None


@dataclass
class HarnessReport:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def top1_hits(self) -> int:
        return sum(1 for r in self.results if r.error is None and r.score.top1)

    @property
    def top2_hits(self) -> int:
        return sum(1 for r in self.results if r.error is None and r.score.top2)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.error is not None)

    @property
    def top1_accuracy(self) -> float:
        return self.top1_hits / self.total if self.total else 0.0

    @property
    def top2_accuracy(self) -> float:
        return self.top2_hits / self.total if self.total else 0.0


def _settings_for(case: FaultCase) -> Settings:
    # cluster_enabled=True so the REAL KubeQueryTools (not the demo stub) runs
    # against the fake client; extractive mode = deterministic, no LLM/network.
    return Settings(
        cluster_enabled=True,
        reasoning_mode="extractive",
        namespace=case.namespace,
        runbook_rag_url=None,
    )


def run_case(case: FaultCase) -> CaseResult:
    """Run one fault case through the real pipeline and score it."""
    try:
        cfg = _settings_for(case)
        store = case.build_store()
        builder = GraphBuilder(cfg, kube_client=FakeKubeClient(store))
        builder.rebuild()
        flow = ReasoningFlow(cfg, graph=builder.graph, builder=builder)
        report = flow.run(case.alert)
        score = score_case(case, report.hypotheses)
        return CaseResult(
            case_id=case.id,
            fault_type=case.fault_type,
            description=case.description,
            expected=case.expected,
            top_cause=score.top_cause,
            score=score,
        )
    except Exception as exc:  # noqa: BLE001 - a harness must never crash on one case
        from rca_agent.eval.scorer import Score as _S
        return CaseResult(
            case_id=case.id, fault_type=case.fault_type,
            description=case.description, expected=case.expected,
            top_cause="", score=_S(False, False, 0, "", 0), error=repr(exc))


def run_harness(cases: list[FaultCase] | None = None) -> HarnessReport:
    """Run the whole fault library (or a provided subset) and aggregate."""
    cases = cases if cases is not None else FAULT_LIBRARY
    return HarnessReport(results=[run_case(c) for c in cases])
