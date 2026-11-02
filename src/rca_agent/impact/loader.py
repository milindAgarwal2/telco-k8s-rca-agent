"""Parse the service-area mapping workbook into structured records.

Reads only two sheets:
  * "20-section map"  -> ServiceArea per numbered section (service + direct pods)
  * "Pod map"         -> per-pod component / section / relationship / confidence

Pod names are matched on a STEM (the name with the Kubernetes replicaset/pod
hash suffix stripped) so a live pod whose hash has rolled still resolves to the
workbook row. The "Alert mapping detail" sheet is intentionally ignored -- it
is out of scope for this high-confidence, area-only feature.
"""
from __future__ import annotations

import re

from openpyxl import load_workbook

from rca_agent.impact.models import ServiceArea, ServiceAreaImpact

_SECTION_SHEET = "20-section map"
_POD_SHEET = "Pod map"

# Two trailing hash-ish segments: "<name>-<rshash>-<podhash>" (deploys) or one
# trailing ordinal/hash for statefulsets ("<name>-0") / single-hash configurers.
_POD_HASH_SUFFIX = re.compile(
    r"-(?:[0-9a-f]{6,10})(?:-(?:[0-9a-z]{5}|[0-9]+))?$|-[0-9]+$"
)
_NO_POD_MARKERS = ("no clear", "no pod", "not identifiable")


def pod_stem(name: str) -> str:
    """Strip the trailing K8s replicaset/pod hash (and statefulset ordinal) so
    'eric-x-85c5f46fc5-9zspm' and 'eric-x-77abc12345-qqqqq' share a stem."""
    if not name:
        return ""
    name = name.strip()
    prev = None
    # Apply up to twice to remove both the replicaset hash and the pod suffix.
    while prev != name:
        prev = name
        name = _POD_HASH_SUFFIX.sub("", name, count=1)
    return name


def _split_pods(cell: str | None) -> list[str]:
    if not cell:
        return []
    text = str(cell)
    if any(m in text.lower() for m in _NO_POD_MARKERS):
        return []
    return [p.strip() for p in text.replace("\r", "\n").split("\n") if p.strip()]


def _header_map(ws) -> dict[str, int]:
    """Map lowercased header text -> 1-based column index (robust to wording)."""
    out: dict[str, int] = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=c).value
        if v is not None:
            out[str(v).strip().lower()] = c
    return out


def _col(hmap: dict[str, int], *needles: str) -> int | None:
    for key, idx in hmap.items():
        if all(n in key for n in needles):
            return idx
    return None


def parse_service_areas(wb) -> list[ServiceArea]:
    ws = wb[_SECTION_SHEET]
    h = _header_map(ws)
    c_sec = _col(h, "§") or _col(h, "pdf") or 1
    c_svc = _col(h, "service group") or _col(h, "service / service") or 2
    c_comp = _col(h, "component") or 3
    c_direct = _col(h, "mapped directly") or _col(h, "directly") or 4
    areas: list[ServiceArea] = []
    for r in range(2, ws.max_row + 1):
        svc = ws.cell(row=r, column=c_svc).value
        if not svc:
            continue
        areas.append(ServiceArea(
            section=str(ws.cell(row=r, column=c_sec).value or "").strip(),
            service=str(svc).strip(),
            components=str(ws.cell(row=r, column=c_comp).value or "").strip(),
            direct_pods=_split_pods(ws.cell(row=r, column=c_direct).value),
        ))
    return areas


def parse_pod_rows(wb) -> list[dict]:
    """Raw per-pod rows from the Pod map (name/component/section/rel/confidence)."""
    ws = wb[_POD_SHEET]
    h = _header_map(ws)
    c_name = _col(h, "pod name") or _col(h, "pod") or 1
    c_comp = _col(h, "mapped service") or _col(h, "component") or 2
    c_sec = _col(h, "section") or 3
    c_rel = _col(h, "relationship") or 4
    c_conf = _col(h, "confidence") or 5
    rows: list[dict] = []
    for r in range(2, ws.max_row + 1):
        name = ws.cell(row=r, column=c_name).value
        if not name:
            continue
        rows.append({
            "pod": str(name).strip(),
            "component": str(ws.cell(row=r, column=c_comp).value or "").strip(),
            "section_raw": str(ws.cell(row=r, column=c_sec).value or "").strip(),
            "relationship_type": str(ws.cell(row=r, column=c_rel).value or "").strip(),
            "confidence": str(ws.cell(row=r, column=c_conf).value or "Unknown").strip()
            or "Unknown",
        })
    return rows


def _section_number(section_raw: str) -> str:
    """Extract the bare section number from '§18 VPN Gateway' / '18' / 'section 18'."""
    m = re.search(r"\d+", section_raw or "")
    return m.group(0) if m else ""


def build_impacts(wb) -> tuple[list[ServiceAreaImpact], list[ServiceArea]]:
    """Build the per-pod impact records + the service-area list from a workbook."""
    areas = parse_service_areas(wb)
    pod_rows = parse_pod_rows(wb)

    # service-area pod counts keyed by section number and by service name.
    area_count_by_section: dict[str, int] = {}
    area_name_by_section: dict[str, str] = {}
    for a in areas:
        area_count_by_section[a.section] = len(a.direct_pods)
        area_name_by_section[a.section] = a.service

    # component sibling counts: how many pod rows share the same component.
    comp_counts: dict[str, int] = {}
    for row in pod_rows:
        comp = row["component"]
        if comp and comp.lower() not in ("", "unmapped"):
            comp_counts[comp] = comp_counts.get(comp, 0) + 1

    impacts: list[ServiceAreaImpact] = []
    for row in pod_rows:
        comp = row["component"]
        rel = row["relationship_type"].lower()
        unmapped = (not comp) or rel == "unmapped" or comp.lower() == "unmapped"
        sec = _section_number(row["section_raw"])
        service = area_name_by_section.get(sec, "")
        # Fall back to the section_raw text for the service area name if the
        # section map didn't resolve (keeps the human-readable area).
        if not service and row["section_raw"]:
            service = re.sub(r"^[§\s0-9]+", "", row["section_raw"]).strip()
        impacts.append(ServiceAreaImpact(
            pod=row["pod"],
            mapped=not unmapped,
            component=comp if not unmapped else "",
            service_area=service if not unmapped else "",
            section=sec if not unmapped else "",
            relationship_type=row["relationship_type"],
            confidence=row["confidence"] if not unmapped else "Unknown",
            component_sibling_count=comp_counts.get(comp, 0) if not unmapped else 0,
            service_area_pod_count=area_count_by_section.get(sec, 0) if not unmapped else 0,
        ))
    return impacts, areas


def load_workbook_impacts(path: str) -> tuple[list[ServiceAreaImpact], list[ServiceArea]]:
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        return build_impacts(wb)
    finally:
        wb.close()
