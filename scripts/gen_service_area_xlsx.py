"""Generate service-area-impact.xlsx from the mapping workbook.

Scoped output: for every pod, the service AREA it belongs to + factual
redundancy counts. No alerts, no severity, no downstream inference.

    .venv/bin/python scripts/gen_service_area_xlsx.py \
        resilience_common_services_pod_mapping.xlsx service-area-impact.xlsx \
        [--live cobra-pods-<ns>.xlsx]

The optional --live spreadsheet (produced by the earlier pod dump) adds a
"Current status" column and a "Live Risk" sheet listing NOT-RUNNING pods with
their service area -- a pure spreadsheet join, still offline.
"""
from __future__ import annotations

import argparse
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from rca_agent.impact.loader import load_workbook_impacts, pod_stem

NAVY = "1F3A6B"
HDR_FILL = PatternFill("solid", fgColor=NAVY)
HDR_FONT = Font(bold=True, color="FFFFFF")
GREY_FILL = PatternFill("solid", fgColor="E9ECEF")   # UNKNOWN rows
BAD_FILL = PatternFill("solid", fgColor="F8D7DA")    # not-running (live)


def _live_status(path: str) -> dict[str, str]:
    """Read a cobra-pods xlsx -> {pod_name: STATUS}. Best-effort."""
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb["Pods"] if "Pods" in wb.sheetnames else wb[wb.sheetnames[0]]
        # find header row (NAME / STATUS)
        name_c = status_c = None
        hdr_row = 1
        for r in range(1, min(10, ws.max_row) + 1):
            vals = [str(ws.cell(row=r, column=c).value or "").upper()
                    for c in range(1, ws.max_column + 1)]
            if "NAME" in vals and "STATUS" in vals:
                hdr_row = r
                name_c = vals.index("NAME") + 1
                status_c = vals.index("STATUS") + 1
                break
        if name_c is None:
            return {}
        out: dict[str, str] = {}
        for r in range(hdr_row + 1, ws.max_row + 1):
            name = ws.cell(row=r, column=name_c).value
            if name:
                out[str(name).strip()] = str(ws.cell(row=r, column=status_c).value or "")
        return out
    finally:
        wb.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mapping")
    ap.add_argument("out", nargs="?", default="service-area-impact.xlsx")
    ap.add_argument("--live", help="cobra-pods xlsx to overlay current status")
    args = ap.parse_args()

    impacts, areas = load_workbook_impacts(args.mapping)
    impacts.sort(key=lambda i: (i.service_area or "zzz", i.pod))
    live = _live_status(args.live) if args.live else {}

    wb = Workbook()
    ws = wb.active
    ws.title = "Pod Service Area"

    ws["A1"] = "Service area impacted per pod"
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws["A2"] = (f"{len(impacts)} pods · source: {args.mapping} · "
                f"generated {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    ws["A2"].font = Font(italic=True, size=10, color="666666")

    cols = ["POD", "COMPONENT", "SERVICE AREA", "SECTION", "CONFIDENCE",
            "COMPONENT PODS", "SERVICE AREA PODS"]
    if live:
        cols.append("CURRENT STATUS")
    hr = 4
    for j, col in enumerate(cols, 1):
        c = ws.cell(row=hr, column=j, value=col)
        c.fill = HDR_FILL; c.font = HDR_FONT; c.alignment = Alignment(horizontal="left")

    for i, imp in enumerate(impacts, hr + 1):
        row = [
            imp.pod,
            imp.component or "—",
            imp.service_area or "UNKNOWN",
            imp.section or "—",
            imp.confidence,
            imp.component_sibling_count or "—",
            imp.service_area_pod_count or "—",
        ]
        if live:
            row.append(live.get(imp.pod, live.get(pod_stem(imp.pod), "")))
        for j, val in enumerate(row, 1):
            cell = ws.cell(row=i, column=j, value=val)
            if not imp.mapped:
                cell.fill = GREY_FILL
            if live and j == len(cols):
                st = str(val)
                if st and st not in ("Running", "Completed", "Succeeded", ""):
                    cell.fill = BAD_FILL; cell.font = Font(bold=True, color="842029")

    ws.freeze_panes = ws.cell(row=hr + 1, column=1)
    ws.auto_filter.ref = f"A{hr}:{get_column_letter(len(cols))}{hr + len(impacts)}"
    widths = [58, 30, 22, 9, 12, 16, 18, 18]
    for j in range(1, len(cols) + 1):
        ws.column_dimensions[get_column_letter(j)].width = widths[j - 1]

    # Service Areas summary sheet
    sa = wb.create_sheet("Service Areas")
    sa["A1"] = "Service areas (section map)"; sa["A1"].font = Font(bold=True, size=12, color=NAVY)
    for j, col in enumerate(["SERVICE AREA", "SECTION", "TOTAL PODS", "COMPONENTS"], 1):
        c = sa.cell(row=3, column=j, value=col); c.fill = HDR_FILL; c.font = HDR_FONT
    for i, a in enumerate(sorted(areas, key=lambda x: x.service), 4):
        sa.cell(row=i, column=1, value=a.service)
        sa.cell(row=i, column=2, value=a.section)
        sa.cell(row=i, column=3, value=len(a.direct_pods))
        sa.cell(row=i, column=4, value=a.components)
    for j, w in enumerate([24, 9, 12, 70], 1):
        sa.column_dimensions[get_column_letter(j)].width = w

    # Live Risk sheet (not-running pods + their area)
    if live:
        lr = wb.create_sheet("Live Risk")
        lr["A1"] = "Currently not-running pods and their service area"
        lr["A1"].font = Font(bold=True, size=12, color=NAVY)
        for j, col in enumerate(["POD", "CURRENT STATUS", "SERVICE AREA", "SECTION",
                                 "COMPONENT", "COMPONENT PODS", "SERVICE AREA PODS"], 1):
            c = lr.cell(row=3, column=j, value=col); c.fill = HDR_FILL; c.font = HDR_FONT
        by_pod = {imp.pod: imp for imp in impacts}
        by_stem = {pod_stem(imp.pod): imp for imp in impacts}
        r = 4
        for pod, status in sorted(live.items()):
            if status in ("Running", "Completed", "Succeeded", ""):
                continue
            imp = by_pod.get(pod) or by_stem.get(pod_stem(pod))
            lr.cell(row=r, column=1, value=pod)
            lr.cell(row=r, column=2, value=status)
            lr.cell(row=r, column=3, value=(imp.service_area or "UNKNOWN") if imp else "UNKNOWN")
            lr.cell(row=r, column=4, value=(imp.section or "—") if imp else "—")
            lr.cell(row=r, column=5, value=(imp.component or "—") if imp else "—")
            lr.cell(row=r, column=6, value=(imp.component_sibling_count or "—") if imp else "—")
            lr.cell(row=r, column=7, value=(imp.service_area_pod_count or "—") if imp else "—")
            r += 1
        for j, w in enumerate([58, 18, 22, 9, 30, 16, 18], 1):
            lr.column_dimensions[get_column_letter(j)].width = w

    wb.save(args.out)
    mapped = sum(1 for i in impacts if i.mapped)
    print(f"wrote {args.out}: {len(impacts)} pods ({mapped} mapped, "
          f"{len(impacts) - mapped} UNKNOWN), {len(areas)} service areas"
          + (f", live overlay from {args.live}" if live else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
