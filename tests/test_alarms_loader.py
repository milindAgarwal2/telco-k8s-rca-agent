"""Potential-alarms loader + index example/edge tests.

Mirrors ``tests/test_impact_loader.py`` in style. Runs against the committed
SYNTHETIC fixture (tests/fixtures/make_pod_alarm_fixture.py) that reproduces the
real workbook's shape: a title row (row 1), a disclaimer row (row 2), the 10-column
header (row 3), and data from row 4, including one blank-``Pod name`` row the loader
must skip. Asserted fixture values:
  - eric-pc-vpn-gateway-forwarder-*  -> 3 candidates (2 Direct, 1 Conditional)
  - eric-pc-routing-engine-*         -> 3 candidates (2 Direct, 1 Conditional)
  - eric-sec-certm-*                 -> 1 candidate  (Direct)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rca_agent.alarms.index import PotentialAlarmsIndex, load_potential_alarms_index
from rca_agent.alarms.loader import load_workbook_alarms
from rca_agent.alarms.models import PotentialAlarms
from rca_agent.impact.loader import pod_stem

FIXTURE = str(Path(__file__).parent / "fixtures" / "pod_alarm_mapping_sample.xlsx")

FORWARDER = "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm"
ROUTING = "eric-pc-routing-engine-5d4d546b64-bh9px"
CERTM = "eric-sec-certm-7d8f9dfc56-f7rpv"


@pytest.fixture(scope="module")
def index() -> PotentialAlarmsIndex:
    idx = load_potential_alarms_index(FIXTURE)
    assert idx is not None
    return idx


# ---- loader (R1 AC2, 1.5) --------------------------------------------------

def test_loader_skips_title_disclaimer_and_maps_all_columns():
    # The header-row scan skips the title (row 1) and disclaimer (row 2) rows:
    # if those were read as the header, no "pod name" column would be found and
    # every pod would be dropped. Three mapped pods proves the header at row 3
    # was located and the column mapping ran.
    items = load_workbook_alarms(FIXTURE)
    by_pod = {it.pod: it for it in items}
    assert set(by_pod) == {FORWARDER, ROUTING, CERTM}  # blank-Pod-name row skipped

    # All 10 columns map: pick a fully-populated Direct row and a Conditional
    # row and assert every mapped field is present verbatim from the workbook.
    fwd = by_pod[FORWARDER]
    assert fwd.mapped is True
    assert len(fwd.alarms) == 3

    not_ready = next(a for a in fwd.alarms if a.alarm_name == "Pod Not Ready")
    assert not_ready.workload_key == "pc-vpn-gateway-forwarder"
    assert not_ready.scope == "Individual pod"
    assert not_ready.severity == "Major"
    assert not_ready.raise_condition == \
        "Readiness probe fails for longer than the configured threshold."
    assert not_ready.clear_condition == \
        "Readiness probe succeeds and the pod reports Ready."
    assert not_ready.applicability == ""
    assert "Exact pod name" in not_ready.mapping_basis
    assert not_ready.source_citation == 'Pod related Alarms.pdf -- "Pod Not Ready"'

    conditional = next(a for a in fwd.alarms if not a.is_direct)
    assert conditional.scope == "Workload (container usage across workload)"
    assert conditional.applicability.startswith("Applies only when the workload")
    assert conditional.source_citation == \
        'Workload related Alarms.pdf -- "Memory Pressure"'


def test_loader_orders_direct_before_conditional_stable():
    # R1 AC2 / R2 AC6: within each pod, Direct entries precede Conditional ones,
    # workbook relative order preserved inside each group.
    items = load_workbook_alarms(FIXTURE)
    fwd = next(it for it in items if it.pod == FORWARDER)
    directs = [i for i, a in enumerate(fwd.alarms) if a.is_direct]
    conds = [i for i, a in enumerate(fwd.alarms) if not a.is_direct]
    assert directs == [0, 1]
    assert conds == [2]
    # Direct relative order preserved: Pod Not Ready before Container Restarting.
    assert [a.alarm_name for a in fwd.alarms if a.is_direct] == \
        ["Pod Not Ready", "Container Restarting Repeatedly"]


def test_loader_reload_sees_resupplied_fixture(tmp_path: Path):
    # R1 AC5: the index loads the workbook per lookup, so a re-supplied workbook
    # takes effect on the next load. Copy the fixture to a temp path, load it,
    # then overwrite with an empty workbook and reload -> the change is visible.
    from openpyxl import Workbook, load_workbook

    target = tmp_path / "reloadable.xlsx"
    wb = load_workbook(FIXTURE)
    wb.save(str(target))
    first = load_potential_alarms_index(str(target))
    assert first is not None
    assert len(first) == 3

    # Overwrite with a workbook whose single data pod differs from the original.
    wb2 = Workbook()
    ws = wb2.active
    ws.title = "Pod Alarm Mapping"
    ws.append(["Individual Pod -> Alarm Mapping"])
    ws.append(["disclaimer"])
    ws.append([
        "Pod name", "Name-derived workload/service key", "Alarm name",
        "Alarm scope", "Severity in PDF", "Condition that raises alarm",
        "Clear/reset condition", "Applicability / qualification",
        "Mapping basis", "Source in PDF",
    ])
    ws.append([
        "eric-only-one-pod-abc123-xyz", "only-one", "Only Alarm",
        "Individual pod", "Minor", "raises", "clears", "",
        "Exact pod name match.", 'Pod related Alarms.pdf -- "Only Alarm"',
    ])
    wb2.save(str(target))

    second = load_potential_alarms_index(str(target))
    assert second is not None
    assert len(second) == 1
    assert second.by_pod(FORWARDER).mapped is False  # old pod gone on reload
    assert second.by_pod("eric-only-one-pod-abc123-xyz").mapped is True


# ---- index edge cases (R1 AC7) ---------------------------------------------

def test_by_pod_empty_is_unmapped_no_raise(index: PotentialAlarmsIndex):
    imp = index.by_pod("")
    assert imp.mapped is False
    assert imp.alarms == []
    assert imp.pod == ""


def test_by_pod_whitespace_is_unmapped_no_raise(index: PotentialAlarmsIndex):
    imp = index.by_pod("   ")
    assert imp.mapped is False
    assert imp.alarms == []


def test_by_pod_exact(index: PotentialAlarmsIndex):
    imp = index.by_pod(CERTM)
    assert imp.mapped is True
    assert imp.pod == CERTM
    assert [a.alarm_name for a in imp.alarms] == ["Certificate Expiring Soon"]


def test_by_pod_resolves_rolled_hash_via_stem(index: PotentialAlarmsIndex):
    # Same stem, different (fictional) replicaset+pod hash -> still resolves.
    assert pod_stem("eric-pc-vpn-gateway-forwarder-77abc12345-qqzzz") == \
        pod_stem(FORWARDER)
    rolled = "eric-pc-vpn-gateway-forwarder-77abc12345-qqzzz"
    imp = index.by_pod(rolled)
    assert imp.mapped is True
    assert imp.pod == rolled  # carries the queried name
    assert len(imp.alarms) == 3


def test_by_pod_unknown_for_unmapped(index: PotentialAlarmsIndex):
    imp = index.by_pod("totally-not-a-real-pod-123")
    assert imp.mapped is False
    assert imp.alarms == []
    assert "UNKNOWN" in imp.summary_line()


# ---- UNKNOWN distinctness (R3 AC5) -----------------------------------------

def test_unmapped_distinct_from_mapped_zero_alarm():
    # An unmapped result (mapped=False, zero alarms) must be distinguishable
    # from a mapped pod that happens to have zero candidate alarms -- the two
    # are not reported identically.
    unmapped = PotentialAlarmsIndex([]).by_pod("never-in-any-workbook")
    mapped_zero = PotentialAlarms(pod="mapped-but-empty", mapped=True, alarms=[])

    # Same alarm count, but the mapped flag distinguishes them.
    assert len(unmapped.alarms) == len(mapped_zero.alarms) == 0
    assert unmapped.mapped is False
    assert mapped_zero.mapped is True
    assert unmapped.mapped != mapped_zero.mapped

    # The surfaced summary lines are different: UNKNOWN vs a mapped count line.
    assert "UNKNOWN" in unmapped.summary_line()
    assert "UNKNOWN" not in mapped_zero.summary_line()


# ---- factory (mirrors impact graceful-off cases) ---------------------------

def test_load_returns_none_when_no_path():
    assert load_potential_alarms_index(None) is None
    assert load_potential_alarms_index("") is None


def test_load_returns_none_when_missing_file(tmp_path: Path):
    assert load_potential_alarms_index(str(tmp_path / "nope.xlsx")) is None
