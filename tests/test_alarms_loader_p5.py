"""Property-based test P5 for the potential-alarms loader.

Hypothesis property P5: ``build_alarms`` orders a pod's candidate alarms
Direct-first then Conditional, preserving workbook relative order within each
group (a STABLE partition on ``CandidateAlarm.is_direct``). Kept in its own
file so it does not collide with the concurrent P4 test in
``tests/test_alarms_loader_p4.py``.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import Workbook

from rca_agent.alarms.loader import build_alarms

_SHEET = "Pod Alarm Mapping"
_POD = "eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm"

# The 10 columns, in design order (matches the loader's header scan + _col map
# and tests/fixtures/make_pod_alarm_fixture.py).
_HEADER = [
    "Pod name",
    "Name-derived workload/service key",
    "Alarm name",
    "Alarm scope",
    "Severity in PDF",
    "Condition that raises alarm",
    "Clear/reset condition",
    "Applicability / qualification",
    "Mapping basis",
    "Source in PDF",
]

# Mapping-basis values the loader classifies on: is_direct is true iff the basis
# (lowercased) contains "exact pod name".
_DIRECT = "Exact pod name match to a pod-level alarm."
_CONDITIONAL = "Conditional candidate from name-derived workload/service."


def _build_workbook(kinds: list[bool]) -> Workbook:
    """One in-memory workbook: a title row, a disclaimer row, the row-3 header,
    then one data row per entry in ``kinds`` (True => Direct, False =>
    Conditional). Each row's ``Alarm name`` encodes its 0-based input index so
    the test can recover input order after the loader partitions."""
    wb = Workbook()
    ws = wb.active
    ws.title = _SHEET
    ws.append(["Individual Pod -> Alarm Mapping"])  # row 1: title
    ws.append(["Synthetic fixture -- candidates, not confirmed alarms."])  # row 2
    ws.append(_HEADER)  # row 3: header
    for i, is_direct in enumerate(kinds):
        ws.append([
            _POD,
            "pc-vpn-gateway-forwarder",
            f"alarm-{i:04d}",          # encodes the input index
            "Individual pod",
            "Major",
            "Some raise condition.",
            "Some clear condition.",
            "",
            _DIRECT if is_direct else _CONDITIONAL,
            "Source.pdf",
        ])
    return wb


# Feature: potential-alarms, Property 5: Direct-before-Conditional stable ordering
@settings(max_examples=100)
@given(kinds=st.lists(st.booleans(), min_size=0, max_size=12))
def test_p5_direct_before_conditional_stable_partition(kinds: list[bool]) -> None:
    """For a single pod with a mix of Direct/Conditional rows in arbitrary
    order, ``build_alarms`` returns a stable partition: every ``is_direct``
    entry precedes every non-direct entry, and the relative input order is
    preserved within each group.

    Validates: Requirements 2.6
    """
    wb = _build_workbook(kinds)
    results = build_alarms(wb)

    if not kinds:
        # No data rows -> no pod grouped.
        assert results == []
        return

    assert len(results) == 1
    out = results[0].alarms
    # Every generated row is retained (no row dropped or duplicated).
    assert len(out) == len(kinds)

    directs = [a.is_direct for a in out]
    # 1) Partition: all True (Direct) come before all False (Conditional); i.e.
    #    no non-direct entry appears before a direct entry.
    assert directs == sorted(directs, reverse=True)

    # Recover each output entry's original input index from its alarm_name.
    def idx(alarm_name: str) -> int:
        return int(alarm_name.split("-")[1])

    direct_indices = [idx(a.alarm_name) for a in out if a.is_direct]
    cond_indices = [idx(a.alarm_name) for a in out if not a.is_direct]

    # Expected input-order indices for each group, taken from the generated mix.
    expected_direct = [i for i, d in enumerate(kinds) if d]
    expected_cond = [i for i, d in enumerate(kinds) if not d]

    # 2) Stability: relative order within each group matches the input order.
    assert direct_indices == expected_direct
    assert cond_indices == expected_cond
