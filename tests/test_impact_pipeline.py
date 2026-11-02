"""Phase 2 tests: service-area impact wired into the reasoning step/report."""
from __future__ import annotations

from pathlib import Path

from rca_agent.impact.index import load_service_area_index
from rca_agent.models.alert import Alert
from rca_agent.reasoning import steps
from rca_agent.reasoning.state import ReasoningState

FIXTURE = str(Path(__file__).parent / "fixtures" / "service_area_mapping_sample.xlsx")
FORWARDER = "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm"


def _state(resource: str) -> ReasoningState:
    return ReasoningState(
        alert=Alert(labels={"alertname": "KubePodNotReady", "pod": resource}),
        namespace="plantx2avzwcspgc-y-oc-consp-301",
        affected_resource=resource,
    )


def test_build_service_area_attaches_mapped_pod():
    idx = load_service_area_index(FIXTURE)
    state = _state(FORWARDER)
    steps.build_service_area(state, idx)
    sa = state.service_area
    assert sa is not None and sa.mapped is True
    assert sa.service_area == "VPN Gateway"
    assert sa.section == "18"
    assert sa.component_sibling_count == 2
    assert sa.service_area_pod_count == 22
    # one cited impact evidence item was added
    impact_ev = [e for e in state.evidence if e.category == "impact"]
    assert len(impact_ev) == 1
    assert "VPN Gateway" in impact_ev[0].summary
    assert impact_ev[0].citations[0].kind == "impact"


def test_build_service_area_off_when_index_none():
    state = _state(FORWARDER)
    steps.build_service_area(state, None)
    assert state.service_area is None
    assert not [e for e in state.evidence if e.category == "impact"]


def test_build_service_area_unmapped_pod_is_noop():
    idx = load_service_area_index(FIXTURE)
    state = _state("totally-unknown-pod-xyz")
    steps.build_service_area(state, idx)
    assert state.service_area is None  # unmapped -> not attached, no fabrication
    assert not [e for e in state.evidence if e.category == "impact"]


def test_build_service_area_falls_back_to_affected_pods():
    idx = load_service_area_index(FIXTURE)
    state = _state("")  # no primary resource
    state.affected_pods = [FORWARDER]
    steps.build_service_area(state, idx)
    assert state.service_area is not None
    assert state.service_area.service_area == "VPN Gateway"
