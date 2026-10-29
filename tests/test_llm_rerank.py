"""Tests for the local-LLM rerank (assessment #3), fully offline.

The llama.cpp sidecar HTTP call is mocked, so CI never needs a model or network.
Covers: valid reorder+explain applied; guardrails reject unknown/duplicate/
wrong-length orders; malformed/empty responses and sidecar errors fall back to
the extractive order; extractive stays the default when reasoning_mode != 'llm'.
"""
from __future__ import annotations

import json

from rca_agent.config import Settings
from rca_agent.models.incident import Hypothesis, IncidentReport
from rca_agent.reasoning import llm_rerank as lr


def _report() -> IncidentReport:
    return IncidentReport(
        symptom="PodUnhealthy on upf-0",
        affected_resource="upf-0",
        hypotheses=[
            Hypothesis(cause="recent rollout to upf", confidence=0.60,
                       evidence_chain=["symptom", "rollout images: bad:v0"]),
            Hypothesis(cause="upf-0 ImagePullBackOff", confidence=0.55),
            Hypothesis(cause="upf-0 failing health probe", confidence=0.50),
        ],
    )


def _cfg() -> Settings:
    return Settings(reasoning_mode="llm", llm_base_url="http://127.0.0.1:8090")


def _mock_sidecar(monkeypatch, content: str | None):
    """Patch _call_sidecar to return a canned content string (or None)."""
    monkeypatch.setattr(lr, "_call_sidecar", lambda cfg, system, user: content)


# ---- happy path ------------------------------------------------------------

def test_valid_reorder_and_explain_applied(monkeypatch):
    rep = _report()
    # Model says: put id=1 first, then 0, then 2, with explanations.
    _mock_sidecar(monkeypatch, json.dumps({
        "order": [1, 0, 2],
        "explanations": {"0": "A recent rollout changed the image.",
                         "1": "The image cannot be pulled.",
                         "2": "The pod fails its readiness probe."},
    }))
    out = lr.llm_rerank(rep, _cfg())
    assert [h.cause for h in out.hypotheses] == [
        "upf-0 ImagePullBackOff", "recent rollout to upf", "upf-0 failing health probe"]
    assert out.reasoning_mode.startswith("llm-rerank")
    # explanation attached to the (now first) hypothesis
    assert any("LLM explanation:" in s for s in out.hypotheses[0].evidence_chain)


# ---- guardrails: bad orders are rejected, original order kept --------------

def test_unknown_id_in_order_rejected(monkeypatch):
    rep = _report()
    _mock_sidecar(monkeypatch, json.dumps({"order": [0, 1, 9], "explanations": {}}))
    out = lr.llm_rerank(rep, _cfg())
    assert [h.cause for h in out.hypotheses] == [
        "recent rollout to upf", "upf-0 ImagePullBackOff", "upf-0 failing health probe"]
    assert "rejected" in out.reasoning_mode


def test_duplicate_id_in_order_rejected(monkeypatch):
    rep = _report()
    _mock_sidecar(monkeypatch, json.dumps({"order": [0, 0, 1], "explanations": {}}))
    out = lr.llm_rerank(rep, _cfg())
    assert next(h.cause for h in out.hypotheses) == "recent rollout to upf"
    assert "rejected" in out.reasoning_mode


def test_wrong_length_order_rejected(monkeypatch):
    rep = _report()
    _mock_sidecar(monkeypatch, json.dumps({"order": [0, 1], "explanations": {}}))
    out = lr.llm_rerank(rep, _cfg())
    assert len(out.hypotheses) == 3
    assert "rejected" in out.reasoning_mode


# ---- malformed / empty / error -> extractive fallback ----------------------

def test_non_json_response_falls_back(monkeypatch):
    rep = _report()
    _mock_sidecar(monkeypatch, "I think the rollout did it, no JSON here.")
    out = lr.llm_rerank(rep, _cfg())
    assert next(h.cause for h in out.hypotheses) == "recent rollout to upf"
    assert "invalid" in out.reasoning_mode


def test_sidecar_unavailable_falls_back(monkeypatch):
    rep = _report()
    _mock_sidecar(monkeypatch, None)  # connection error / timeout
    out = lr.llm_rerank(rep, _cfg())
    assert next(h.cause for h in out.hypotheses) == "recent rollout to upf"
    assert "unavailable" in out.reasoning_mode


def test_no_hypotheses_is_safe(monkeypatch):
    rep = IncidentReport(symptom="x", affected_resource="x", hypotheses=[])
    _mock_sidecar(monkeypatch, None)
    out = lr.llm_rerank(rep, _cfg())
    assert out.hypotheses == []


# ---- flow integration: extractive stays default ---------------------------

def test_flow_extractive_mode_does_not_call_llm(monkeypatch):
    from rca_agent.config import Settings as S
    from rca_agent.graph.builder import GraphBuilder
    from rca_agent.models.alert import Alert
    from rca_agent.reasoning.flow import ReasoningFlow

    called = {"n": 0}
    monkeypatch.setattr(lr, "_call_sidecar",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or None)
    cfg = S(reasoning_mode="extractive")  # default
    b = GraphBuilder(cfg); b.rebuild()
    flow = ReasoningFlow(cfg, graph=b.graph, builder=b)
    flow.run(Alert(status="firing", labels={"alertname": "X", "pod": "upf-0"}))
    assert called["n"] == 0  # LLM never called in extractive mode


def test_validate_order_helper():
    assert lr._validate_order([2, 0, 1], 3) == [2, 0, 1]
    assert lr._validate_order([0, 1], 3) is None
    assert lr._validate_order([0, 1, 3], 3) is None
    assert lr._validate_order("nope", 3) is None
