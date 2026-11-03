"""Tests for LLM runbook next-step synthesis (grounded, cited, guarded).

The sidecar is mocked (no live LLM needed) so these run in CI. They verify the
guardrails: a valid choice yields a grounded + cited step; an out-of-range or
-1 choice, unparseable output, or sidecar failure all fall back to the raw
retrieved hits (never fabricate a source).

NOTE: synthesize_next_step imports ``_call_sidecar`` from
``rca_agent.reasoning.llm_rerank`` at call time, so we patch it THERE (its
definition site), not on runbook_synth.
"""
from __future__ import annotations

from rca_agent.config import Settings
from rca_agent.rag.runbook_retriever import RunbookHit
from rca_agent.reasoning import runbook_synth

_SIDECAR = "rca_agent.reasoning.llm_rerank._call_sidecar"


def _hits() -> list[RunbookHit]:
    return [
        RunbookHit(
            title="doc.pdf",
            snippet="Example pod spec with Readiness: httpGet path /check port 8080.",
            source="doc.pdf#chunk37",
        ),
        RunbookHit(
            title="doc.pdf",
            snippet="Pod Not Ready. Diagnostics: a failing readiness probe with "
                    "context deadline exceeded usually means the app is slow to "
                    "answer /health; raise timeoutSeconds or check app health.",
            source="doc.pdf#chunk16",
        ),
    ]


def _cfg() -> Settings:
    return Settings(reasoning_mode="llm", llm_base_url="http://127.0.0.1:1")


def test_synth_picks_remedy_and_cites(monkeypatch):
    # LLM picks index 1 (the real remedy), not the example at 0.
    monkeypatch.setattr(
        _SIDECAR,
        lambda *a, **k: '{"choice": 1, "next_step": "Increase the readiness '
                        'probe timeoutSeconds and verify /health responds."}',
    )
    result = runbook_synth.synthesize_next_step("readiness probe failed", _hits(), _cfg())
    assert result is not None
    text, chosen = result
    assert "timeoutSeconds" in text
    assert chosen.source == "doc.pdf#chunk16"  # cited the chosen chunk


def test_synth_rejects_out_of_range_choice(monkeypatch):
    monkeypatch.setattr(_SIDECAR, lambda *a, **k: '{"choice": 9, "next_step": "do something"}')
    assert runbook_synth.synthesize_next_step("x", _hits(), _cfg()) is None


def test_synth_rejects_negative_choice(monkeypatch):
    # choice = -1 means "no real remedy"; must not fabricate.
    monkeypatch.setattr(_SIDECAR, lambda *a, **k: '{"choice": -1, "next_step": "irrelevant"}')
    assert runbook_synth.synthesize_next_step("x", _hits(), _cfg()) is None


def test_synth_falls_back_on_sidecar_failure(monkeypatch):
    monkeypatch.setattr(_SIDECAR, lambda *a, **k: None)
    assert runbook_synth.synthesize_next_step("x", _hits(), _cfg()) is None


def test_synth_handles_unparseable_output(monkeypatch):
    monkeypatch.setattr(_SIDECAR, lambda *a, **k: "not json at all")
    assert runbook_synth.synthesize_next_step("x", _hits(), _cfg()) is None


def test_synth_extracts_embedded_json(monkeypatch):
    # Model wraps JSON in prose -> we still extract it.
    monkeypatch.setattr(
        _SIDECAR,
        lambda *a, **k: 'Here is my answer: {"choice": 0, "next_step": "Check the spec."} done',
    )
    result = runbook_synth.synthesize_next_step("x", _hits(), _cfg())
    assert result is not None
    assert result[1].source == "doc.pdf#chunk37"


def test_synth_empty_hits_returns_none():
    assert runbook_synth.synthesize_next_step("x", [], _cfg()) is None
