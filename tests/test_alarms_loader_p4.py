"""Property-based test P4 for the potential-alarms workbook loader.

Hypothesis property P4: grouping count equals matching workbook rows. Kept in
its own file (``_p4``) so it does not collide with the concurrently-authored P5
ordering test (``_p5``) or the models P6/P7 tests.

The workbook is built in memory with ``openpyxl.Workbook()`` matching the real
sheet shape the loader scans (title row 1, disclaimer row 2, header row 3, data
from row 4) so ``build_alarms(wb)`` can be exercised directly with no file I/O.
"""
from __future__ import annotations

import openpyxl
from hypothesis import given, settings
from hypothesis import strategies as st

from rca_agent.alarms.loader import _ALARM_SHEET, build_alarms

# The 10 columns in design order, header text verbatim as the loader's _col
# substring matcher expects to find them.
_HEADERS = [
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

# Mapping-basis values mixing Direct ("exact pod name ...") and Conditional. P4
# is about COUNT and field preservation, not ordering, so either basis is fine.
_BASIS = st.sampled_from([
    "Exact pod name match",
    "Conditional candidate (workload-derived)",
])

_TEXT = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    max_size=24,
)
# Pod names: non-blank after stripping, so the loader never treats them as the
# blank-pod rows it must skip.
_POD = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="-",
    ),
    min_size=1,
    max_size=18,
).filter(lambda s: s.strip() != "")


def _row_fields(draw: st.DataObject, basis: str) -> dict[str, str]:
    """Draw the eight mapped payload fields (plus workload key) for one row.

    The loader strips every cell value (``_cell`` applies ``str.strip``), so the
    expected values are stripped here to match that documented contract -- the
    property under test is that the loader preserves each (stripped) cell value
    verbatim, not that it retains incidental surrounding whitespace.
    """
    return {
        "workload_key": draw.draw(_TEXT).strip(),
        "alarm_name": draw.draw(_TEXT).strip(),
        "scope": draw.draw(_TEXT).strip(),
        "severity": draw.draw(_TEXT).strip(),
        "raise_condition": draw.draw(_TEXT).strip(),
        "clear_condition": draw.draw(_TEXT).strip(),
        "applicability": draw.draw(_TEXT).strip(),
        "mapping_basis": basis,
        "source_citation": draw.draw(_TEXT).strip(),
    }


def _fields_of(alarm) -> dict[str, str]:
    """Project a CandidateAlarm to the comparable mapped fields (order-free)."""
    return {
        "workload_key": alarm.workload_key,
        "alarm_name": alarm.alarm_name,
        "scope": alarm.scope,
        "severity": alarm.severity,
        "raise_condition": alarm.raise_condition,
        "clear_condition": alarm.clear_condition,
        "applicability": alarm.applicability,
        "mapping_basis": alarm.mapping_basis,
        "source_citation": alarm.source_citation,
    }


def _build_workbook(rows: list[dict[str, str] | None]):
    """Build an in-memory workbook matching the loader's scanned shape.

    ``rows`` entries: a dict renders a full data row (keyed on header text); a
    ``None`` entry renders a blank-``Pod name`` row that the loader must skip.
    Row 1 = title, row 2 = disclaimer, row 3 = header, data from row 4.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = _ALARM_SHEET
    ws.append(["Pod Alarm Mapping (title row)"])          # row 1: title
    ws.append(["Candidate associations - not confirmed"])  # row 2: disclaimer
    ws.append(list(_HEADERS))                              # row 3: header
    for row in rows:
        if row is None:
            # Blank Pod name, but other columns populated: must contribute no
            # entry. "Skipped" markers prove such rows are not silently kept.
            ws.append(["", "wk", "al", "sc", "sev", "rc", "cc", "ap", "basis", "src"])
        else:
            ws.append([
                row["pod"],
                row["workload_key"],
                row["alarm_name"],
                row["scope"],
                row["severity"],
                row["raise_condition"],
                row["clear_condition"],
                row["applicability"],
                row["mapping_basis"],
                row["source_citation"],
            ])
    return wb


# Feature: potential-alarms, Property 4: Grouping count equals matching workbook rows
@settings(max_examples=100)
@given(data=st.data())
def test_p4_grouping_count_equals_matching_rows(data: st.DataObject) -> None:
    """For every pod with N non-blank rows, the loaded PotentialAlarms has
    mapped=True and exactly N CandidateAlarm entries carrying every mapped
    field; blank-``Pod name`` rows contribute no entry.

    Validates: Requirements 1.3, 2.4, 3.3
    """
    # One to three distinct pods, each with 1..6 data rows.
    pods = data.draw(
        st.lists(_POD, min_size=1, max_size=3, unique_by=lambda s: s.strip()),
        label="pods",
    )
    expected: dict[str, list[dict[str, str]]] = {}
    tagged_rows: list[dict[str, str]] = []
    for pod in pods:
        pod_key = pod.strip()
        n = data.draw(st.integers(min_value=1, max_value=6), label=f"n[{pod_key}]")
        expected[pod_key] = []
        for i in range(n):
            basis = data.draw(_BASIS, label=f"basis[{pod_key}][{i}]")
            fields = _row_fields(data, basis)
            # Make each row's mapped projection unique so an order-free multiset
            # comparison cannot be satisfied by a coincidental duplicate: fold a
            # unique token into source_citation (a verbatim field).
            fields["source_citation"] = f"{fields['source_citation']}|{pod_key}#{i}"
            expected[pod_key].append(fields)
            tagged_rows.append({"pod": pod, **fields})

    # Interleave blank-Pod-name rows that must be skipped: at least one, placed
    # across the sequence (including at the end) so skipping is exercised at the
    # group boundaries the loader iterates.
    blank_count = data.draw(st.integers(min_value=1, max_value=3), label="blanks")
    rows: list[dict[str, str] | None] = list(tagged_rows)
    for _ in range(blank_count):
        pos = data.draw(st.integers(min_value=0, max_value=len(rows)), label="blank_pos")
        rows.insert(pos, None)

    results = build_alarms(_build_workbook(rows))

    by_pod = {r.pod: r for r in results}

    # Blank-Pod-name rows never create a pod entry.
    assert set(by_pod) == set(expected)
    # The blank-row marker payload never leaks into any produced alarm.
    for record in results:
        for alarm in record.alarms:
            assert alarm.source_citation != "src"

    for pod_key, expected_rows in expected.items():
        record = by_pod[pod_key]
        # mapped=True for every grouped pod.
        assert record.mapped is True
        # Exactly N entries -- grouping count equals the matching rows.
        assert len(record.alarms) == len(expected_rows)
        # Every mapped field round-trips from its row (order-free: the loader
        # reorders Direct-before-Conditional, so compare as multisets keyed on
        # the unique source_citation token).
        got = {a.source_citation: _fields_of(a) for a in record.alarms}
        assert len(got) == len(record.alarms)  # tokens stayed unique end to end
        want = {r["source_citation"]: r for r in expected_rows}
        assert got == want
