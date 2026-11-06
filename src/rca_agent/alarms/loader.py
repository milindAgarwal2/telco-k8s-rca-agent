"""Parse the curated pod-alarm mapping workbook into structured records.

Reads only the "Pod Alarm Mapping" sheet -> one PotentialAlarms per pod, each
carrying the candidate alarms (one per data row) that could have been raised
for that pod. These are CANDIDATE associations from a reviewed mapping -- never
observed, confirmed, or active alarms.

This loader is a deliberate near-clone of ``impact/loader.py``. It differs only
where the workbook differs: the real header is not on row 1 (row 1 is a title,
row 2 a disclaimer, row 3 the header), so a small header-row scan locates it
before the same ``_col`` substring column mapping runs. The pod-name stem logic
is REUSED from ``impact/loader`` (single source of truth) rather than
duplicated. The "Alarm Reference" sheet is a definitions dictionary and is
intentionally ignored for the per-pod lookup.
"""
from __future__ import annotations

from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms

_ALARM_SHEET = "Pod Alarm Mapping"
_REFERENCE_SHEET = "Alarm Reference"  # definitions dictionary; OUT OF SCOPE (ignored)


def _find_header_row(ws) -> int:
    """Return the 1-based row whose first cell lower-strips to 'pod name'.

    Scans from the top so a title row + disclaimer row above the header are
    skipped. Defaults to row 1 if no such row is found (mirrors impact's row-1
    assumption as a fallback)."""
    for r in range(1, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        if v is not None and str(v).strip().lower() == "pod name":
            return r
    return 1


def _header_map(ws, header_row: int) -> dict[str, int]:
    """Map lowercased header text -> 1-based column index at the located header
    row (impact's _header_map hard-codes row 1; this takes the row)."""
    out: dict[str, int] = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=c).value
        if v is not None:
            out[str(v).strip().lower()] = c
    return out


def _col(hmap: dict[str, int], *needles: str) -> int | None:
    """First column whose lowered header contains all needles (verbatim reuse
    of impact's substring matcher)."""
    for key, idx in hmap.items():
        if all(n in key for n in needles):
            return idx
    return None


def _cell(ws, row: int, col: int | None) -> str:
    """Stripped string value of a cell, or '' when the column is absent/empty."""
    if col is None:
        return ""
    v = ws.cell(row=row, column=col).value
    return str(v).strip() if v is not None else ""


def build_alarms(wb) -> list[PotentialAlarms]:
    """Group every data row (header_row+1 .. max_row) by the exact 'Pod name'
    value into one PotentialAlarms per pod.

    Rows with a blank Pod name are skipped. Each row becomes one CandidateAlarm
    mapped by _col. Within each pod, alarms are ordered Direct-first then
    Conditional, stable within each group; mapped=True for every grouped pod."""
    ws = wb[_ALARM_SHEET]
    header_row = _find_header_row(ws)
    h = _header_map(ws, header_row)

    c_pod = _col(h, "pod name") or 1
    c_workload = _col(h, "name-derived") or _col(h, "workload")
    c_alarm = _col(h, "alarm name")
    c_scope = _col(h, "alarm scope") or _col(h, "scope")
    c_sev = _col(h, "severity")
    c_raise = _col(h, "condition", "raise") or _col(h, "raises")
    c_clear = _col(h, "clear") or _col(h, "reset")
    c_applic = _col(h, "applicability") or _col(h, "qualification")
    c_basis = _col(h, "mapping basis") or _col(h, "basis")
    c_source = _col(h, "source")

    # Preserve first-seen pod order and workbook row order within each pod.
    order: list[str] = []
    grouped: dict[str, list[CandidateAlarm]] = {}
    for r in range(header_row + 1, ws.max_row + 1):
        pod = _cell(ws, r, c_pod)
        if not pod:
            continue
        if pod not in grouped:
            grouped[pod] = []
            order.append(pod)
        grouped[pod].append(CandidateAlarm(
            alarm_name=_cell(ws, r, c_alarm),
            scope=_cell(ws, r, c_scope),
            severity=_cell(ws, r, c_sev),
            raise_condition=_cell(ws, r, c_raise),
            clear_condition=_cell(ws, r, c_clear),
            applicability=_cell(ws, r, c_applic),
            mapping_basis=_cell(ws, r, c_basis),
            source_citation=_cell(ws, r, c_source),
            workload_key=_cell(ws, r, c_workload),
        ))

    results: list[PotentialAlarms] = []
    for pod in order:
        alarms = grouped[pod]
        # Stable partition: Direct (is_direct) first, Conditional after, each
        # preserving workbook relative order.
        ordered = [a for a in alarms if a.is_direct] + [a for a in alarms if not a.is_direct]
        results.append(PotentialAlarms(pod=pod, mapped=True, alarms=ordered))
    return results


def load_workbook_alarms(path: str) -> list[PotentialAlarms]:
    # Import openpyxl lazily: this module is imported transitively by
    # models.incident (hence the whole app), so a missing openpyxl must NOT
    # crash startup -- only an actual workbook load should require it. The
    # index factory catches the ImportError and treats the feature as inert.
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        return build_alarms(wb)
    finally:
        wb.close()
