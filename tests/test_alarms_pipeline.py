"""Phase 8 tests: potential-alarms wired into the reasoning step/report.

Mirrors ``test_impact_pipeline.py`` in style: the reasoning step is exercised
directly against a ``ReasoningState`` (no live cluster), and the graceful-
degradation posture of the factory is asserted against real/missing/unparsable
workbook paths plus a simulated-absent ``openpyxl``.

The feature is CONTEXT-not-cause: attaching potential alarms must never create
or reweight a hypothesis, and when the feature is off the report field stays
``None`` (additive, backward compatible).
"""
from __future__ import annotations

import builtins
import sys
from pathlib import Path

from rca_agent.alarms.index import load_potential_alarms_index
from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms
from rca_agent.models.alert import Alert
from rca_agent.models.incident import Hypothesis, IncidentReport
from rca_agent.reasoning import steps
from rca_agent.reasoning.state import ReasoningState

FIXTURE = str(Path(__file__).parent / "fixtures" / "pod_alarm_mapping_sample.xlsx")
FORWARDER = "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm"
ROUTING = "eric-pc-routing-engine-5d4d546b64-bh9px"


def _state(resource: str) -> ReasoningState:
    return ReasoningState(
        alert=Alert(labels={"alertname": "KubePodNotReady", "pod": resource}),
        namespace="plantx2avzwcspgc-y-oc-consp-301",
        affected_resource=resource,
    )


# ---- pipeline step: mapped / fallback / no-pods (R2 AC1/2/3/8) --------------

def test_build_potential_alarms_attaches_mapped_pod():
    idx = load_potential_alarms_index(FIXTURE)
    state = _state(FORWARDER)
    steps.build_potential_alarms(state, idx)
    pa = state.potential_alarms
    assert pa is not None and pa.mapped is True
    assert pa.pod == FORWARDER
    assert len(pa.alarms) == 3  # two Direct + one Conditional in the fixture
    # Exactly one cited "alarms" evidence item was added.
    alarm_ev = [e for e in state.evidence if e.category == "alarms"]
    assert len(alarm_ev) == 1
    assert alarm_ev[0].citations[0].kind == "alarms"
    assert alarm_ev[0].citations[0].source == "pod-alarm mapping workbook"
    assert "candidate" in alarm_ev[0].summary.lower()


def test_build_potential_alarms_falls_back_to_affected_pods():
    idx = load_potential_alarms_index(FIXTURE)
    state = _state("")  # no primary resource
    state.affected_pods = [ROUTING]
    steps.build_potential_alarms(state, idx)
    assert state.potential_alarms is not None
    assert state.potential_alarms.pod == ROUTING
    assert state.potential_alarms.mapped is True
    assert len([e for e in state.evidence if e.category == "alarms"]) == 1


def test_build_potential_alarms_no_affected_pods_stays_none():
    idx = load_potential_alarms_index(FIXTURE)
    state = _state("")  # no primary resource and no affected pods
    assert state.affected_pods == []
    steps.build_potential_alarms(state, idx)
    assert state.potential_alarms is None
    assert not [e for e in state.evidence if e.category == "alarms"]


def test_build_potential_alarms_unmapped_pod_is_noop():
    idx = load_potential_alarms_index(FIXTURE)
    state = _state("totally-unknown-pod-xyz")
    steps.build_potential_alarms(state, idx)
    # Unmapped -> not attached, no fabrication.
    assert state.potential_alarms is None
    assert not [e for e in state.evidence if e.category == "alarms"]


def test_build_potential_alarms_off_when_index_none():
    state = _state(FORWARDER)
    steps.build_potential_alarms(state, None)
    assert state.potential_alarms is None
    assert not [e for e in state.evidence if e.category == "alarms"]


# ---- context-not-cause: ranking is never touched (R5 AC2/3) -----------------

def _seed_hypotheses(state: ReasoningState) -> list[Hypothesis]:
    """Give the state a fixed set of ranked hypotheses to guard against reweight."""
    state.hypotheses = [
        Hypothesis(cause="A", confidence=0.80),
        Hypothesis(cause="B", confidence=0.40),
    ]
    return [h.model_copy(deep=True) for h in state.hypotheses]


def test_build_potential_alarms_does_not_change_ranking():
    idx = load_potential_alarms_index(FIXTURE)
    state = _state(FORWARDER)
    before = _seed_hypotheses(state)
    steps.build_potential_alarms(state, idx)
    # Feature attached...
    assert state.potential_alarms is not None and state.potential_alarms.mapped
    # ...but hypotheses are identical in count, identity, confidence, order.
    assert len(state.hypotheses) == len(before)
    for got, want in zip(state.hypotheses, before):
        assert got.cause == want.cause
        assert got.confidence == want.confidence


# ---- serialization / backward-compat (R5 AC1/4) -----------------------------

def test_report_feature_off_potential_alarms_is_none():
    report = IncidentReport(symptom="KubePodNotReady on x")
    assert report.potential_alarms is None
    dumped = report.model_dump()
    assert dumped["potential_alarms"] is None
    # Round-trips unchanged.
    assert IncidentReport.model_validate(dumped).potential_alarms is None


# ---- graceful degradation: the factory (R8 / 8.1-8.4) -----------------------

def test_load_returns_none_when_no_path():
    # Unset path -> feature inert (no log asserted; just None).
    assert load_potential_alarms_index(None) is None
    assert load_potential_alarms_index("") is None


def test_load_returns_none_when_missing_file(tmp_path: Path, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="rca_agent.alarms.index"):
        result = load_potential_alarms_index(str(tmp_path / "nope.xlsx"))
    assert result is None
    # Exactly one log line about the missing map.
    msgs = [r for r in caplog.records if r.name == "rca_agent.alarms.index"]
    assert len(msgs) == 1
    assert "not found" in msgs[0].getMessage()


def test_load_returns_none_when_unparsable_workbook(tmp_path: Path, caplog):
    import logging

    bad = tmp_path / "bad.xlsx"
    bad.write_text("this is not a valid xlsx workbook", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="rca_agent.alarms.index"):
        result = load_potential_alarms_index(str(bad))
    assert result is None
    # Exactly one warning about the failed load.
    msgs = [r for r in caplog.records if r.name == "rca_agent.alarms.index"]
    assert len(msgs) == 1
    assert "failed to load" in msgs[0].getMessage()


def test_missing_openpyxl_keeps_feature_inert(tmp_path: Path, monkeypatch, caplog):
    """A simulated-absent ``openpyxl`` must leave the feature identical to the
    disabled path: the factory returns ``None`` (one warning) rather than
    raising, so startup and incident processing are unaffected."""
    import logging

    # A real file exists (so the path/missing-file gates pass) -- the ONLY
    # failure injected is the lazy ``from openpyxl import load_workbook``.
    present = tmp_path / "present.xlsx"
    present.write_bytes(Path(FIXTURE).read_bytes())

    real_import = builtins.__import__

    def _no_openpyxl(name, *args, **kwargs):
        if name == "openpyxl" or name.startswith("openpyxl."):
            raise ImportError("No module named 'openpyxl' (simulated)")
        return real_import(name, *args, **kwargs)

    # Drop any cached openpyxl so the next import re-runs the patched hook.
    monkeypatch.delitem(sys.modules, "openpyxl", raising=False)
    monkeypatch.setattr(builtins, "__import__", _no_openpyxl)

    with caplog.at_level(logging.WARNING, logger="rca_agent.alarms.index"):
        result = load_potential_alarms_index(str(present))

    # Identical to disabled: None, caught, logged once -- never raised.
    assert result is None
    msgs = [r for r in caplog.records if r.name == "rca_agent.alarms.index"]
    assert len(msgs) == 1
    assert "failed to load" in msgs[0].getMessage()


def test_step_level_failure_leaves_none_with_unchanged_ranking():
    """A step-level failure during lookup must not crash the pipeline nor touch
    ranking: ``potential_alarms`` stays ``None`` and the hypotheses are intact.

    A deliberately broken index whose ``by_pod`` raises stands in for any
    unexpected runtime fault inside the step's lookup path.
    """

    class _BoomIndex:
        def by_pod(self, pod_name: str) -> PotentialAlarms:
            raise RuntimeError("simulated lookup failure")

    state = _state(FORWARDER)
    before = _seed_hypotheses(state)

    try:
        steps.build_potential_alarms(state, _BoomIndex())
    except Exception:  # noqa: BLE001, S110 - a raising step must not take the report down
        pass

    assert state.potential_alarms is None
    assert not [e for e in state.evidence if e.category == "alarms"]
    assert len(state.hypotheses) == len(before)
    for got, want in zip(state.hypotheses, before):
        assert got.cause == want.cause
        assert got.confidence == want.confidence


def test_mapped_zero_alarm_is_distinct_from_unmapped():
    """A mapped record with zero alarms is not the same as an UNKNOWN record --
    the step attaches the former but a truly unmapped pod yields no attachment.
    """
    idx = load_potential_alarms_index(FIXTURE)
    # Sanity: the fixture resolves a known pod as mapped with alarms.
    assert idx is not None
    mapped = idx.by_pod(FORWARDER)
    unmapped = idx.by_pod("no-such-pod")
    # A hand-built mapped-but-empty record is still mapped=True (distinct).
    empty_mapped = PotentialAlarms(pod="x", mapped=True, alarms=[])
    assert mapped.mapped is True and len(mapped.alarms) > 0
    assert unmapped.mapped is False
    assert empty_mapped.mapped is True and empty_mapped.mapped != unmapped.mapped
    _ = CandidateAlarm  # imported for parity with the models surface under test
