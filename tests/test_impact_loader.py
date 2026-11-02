"""Phase 0 tests: service-area mapping loader + index.

Runs against a SYNTHETIC fixture (tests/fixtures/make_service_area_fixture.py)
that reproduces the structure and the asserted values -- no live cluster
inventory is committed. Asserted values:
  - eric-pc-vpn-gateway-forwarder-* -> component "PC VPN Gateway Forwarder",
    service area "VPN Gateway", section 18, confidence High,
    component siblings 2, service-area pods 22.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rca_agent.impact.index import ServiceAreaIndex, load_service_area_index
from rca_agent.impact.loader import load_workbook_impacts, pod_stem

FIXTURE = str(Path(__file__).parent / "fixtures" / "service_area_mapping_sample.xlsx")

FORWARDER = "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm"


@pytest.fixture(scope="module")
def index() -> ServiceAreaIndex:
    idx = load_service_area_index(FIXTURE)
    assert idx is not None
    return idx


# ---- pod_stem ---------------------------------------------------------------

def test_pod_stem_strips_deploy_hashes():
    assert pod_stem("eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm") == \
        "eric-pc-vpn-gateway-forwarder"


def test_pod_stem_strips_statefulset_ordinal():
    assert pod_stem("eric-data-search-engine-data-0") == "eric-data-search-engine-data"


def test_pod_stem_empty():
    assert pod_stem("") == ""


# ---- loader ----------------------------------------------------------------

def test_loader_parses_pods_and_areas():
    impacts, areas = load_workbook_impacts(FIXTURE)
    assert len(impacts) == 23            # 22 VPN Gateway + 1 Certificate Mgmt (synthetic)
    assert any(a.service == "VPN Gateway" for a in areas)
    vpn = next(a for a in areas if a.service == "VPN Gateway")
    assert vpn.section == "18"
    assert len(vpn.direct_pods) == 22


# ---- index.by_pod ----------------------------------------------------------

def test_by_pod_forwarder_exact(index: ServiceAreaIndex):
    imp = index.by_pod(FORWARDER)
    assert imp.mapped is True
    assert imp.component == "PC VPN Gateway Forwarder"
    assert imp.service_area == "VPN Gateway"
    assert imp.section == "18"
    assert imp.confidence == "High"
    assert imp.component_sibling_count == 2
    assert imp.service_area_pod_count == 22


def test_by_pod_resolves_rolled_hash_via_stem(index: ServiceAreaIndex):
    # Same stem, different (fictional) replicaset+pod hash -> still resolves.
    rolled = "eric-pc-vpn-gateway-forwarder-77abc12345-qqzzz"
    imp = index.by_pod(rolled)
    assert imp.mapped is True
    assert imp.service_area == "VPN Gateway"
    assert imp.pod == rolled  # carries the queried name


def test_by_pod_unknown_for_unmapped(index: ServiceAreaIndex):
    imp = index.by_pod("totally-not-a-real-pod-123")
    assert imp.mapped is False
    assert imp.service_area == ""
    assert imp.confidence == "Unknown"


def test_summary_line_mapped_and_unknown(index: ServiceAreaIndex):
    mapped = index.by_pod(FORWARDER).summary_line()
    assert "VPN Gateway" in mapped and "section 18" in mapped
    assert "2 pod(s)" in mapped and "22 pod(s)" in mapped
    unknown = index.by_pod("nope").summary_line()
    assert "UNKNOWN" in unknown


# ---- factory ---------------------------------------------------------------

def test_load_returns_none_when_no_path():
    assert load_service_area_index(None) is None
    assert load_service_area_index("") is None


def test_load_returns_none_when_missing_file(tmp_path: Path):
    assert load_service_area_index(str(tmp_path / "nope.xlsx")) is None
