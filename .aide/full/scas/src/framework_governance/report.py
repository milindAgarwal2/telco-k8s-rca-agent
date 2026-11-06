from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from .models import Assessment, GovernanceStatus


class ReportWriter:
    def __init__(self, output_directory: str | Path):
        self.output = Path(output_directory).resolve()

    def write_all(self, assessment: Assessment) -> dict[str, str]:
        self.output.mkdir(parents=True, exist_ok=True)
        paths = {
            "json": self.output / "framework-governance-report.json",
            "markdown": self.output / "framework-governance-report.md",
            "html": self.output / "framework-governance-report.html",
            "csv": self.output / "framework-governance-findings.csv",
            "cyclonedx": self.output / "framework-inventory.cdx.json",
        }
        paths["json"].write_text(
            json.dumps(assessment.to_dict(), indent=2), encoding="utf-8"
        )
        paths["markdown"].write_text(self._markdown(assessment), encoding="utf-8")
        paths["html"].write_text(self._html(assessment), encoding="utf-8")
        self._csv(assessment, paths["csv"])
        paths["cyclonedx"].write_text(
            json.dumps(self._cyclonedx(assessment), indent=2), encoding="utf-8"
        )
        return {key: str(value) for key, value in paths.items()}

    def _markdown(self, assessment: Assessment) -> str:
        counts = assessment.counts()
        lines = [
            "# Framework Governance Assessment",
            "",
            f"- Repository: `{assessment.scan.repository}`",
            f"- Assessed: {assessment.assessed_at}",
            f"- SCAS catalog mode: `{assessment.catalog_mode}`",
            f"- Policy version: `{assessment.policy_version}`",
            f"- Compliance score: **{assessment.compliance_score()}%**",
            "",
            "## Summary",
            "",
            "| Green | Amber | Yellow | Red | Grey |",
            "|---:|---:|---:|---:|---:|",
            f"| {counts['green']} | {counts['amber']} | {counts['yellow']} | {counts['red']} | {counts['grey']} |",
            "",
            "## Findings",
            "",
            "| Status | Component | Detected | SCAS/Target | Category | Reason | Recommendation | Evidence |",
            "|---|---|---|---|---|---|---|---|",
        ]
        order = {
            GovernanceStatus.RED: 0,
            GovernanceStatus.GREY: 1,
            GovernanceStatus.AMBER: 2,
            GovernanceStatus.YELLOW: 3,
            GovernanceStatus.GREEN: 4,
        }
        for finding in sorted(assessment.findings, key=lambda item: (order[item.status], item.component.name)):
            record = finding.catalog_record
            target = "-"
            if record:
                target = record.recommended_version or record.version or "-"
            evidence = "<br>".join(_md(value) for value in finding.component.evidence[:5])
            lines.append(
                "| {status} | {name} | {version} | {target} | {category} | {reason} | {recommendation} | {evidence} |".format(
                    status=finding.status.value.upper(),
                    name=_md(finding.component.name),
                    version=_md(finding.component.version or "Unresolved"),
                    target=_md(target),
                    category=_md(finding.component.category),
                    reason=_md(finding.reason),
                    recommendation=_md(finding.recommendation),
                    evidence=evidence,
                )
            )
        if assessment.catalog_errors or assessment.scan.warnings:
            lines.extend(["", "## Warnings", ""])
            for warning in assessment.catalog_errors + assessment.scan.warnings:
                lines.append(f"- {_md(warning)}")
        return "\n".join(lines) + "\n"

    def _html(self, assessment: Assessment) -> str:
        counts = assessment.counts()
        rows = []
        for finding in assessment.findings:
            record = finding.catalog_record
            target = record.recommended_version or record.version if record else "-"
            status = finding.status.value
            rows.append(
                f"<tr data-status='{status}'>"
                f"<td data-sort='{status}'><span class='badge {status}'>{status.upper()}</span></td>"
                f"<td data-sort='{html.escape(finding.component.name.lower())}'>{html.escape(finding.component.name)}</td>"
                f"<td data-sort='{html.escape((finding.component.version or '').lower())}'>{html.escape(finding.component.version or 'Unresolved')}</td>"
                f"<td data-sort='{html.escape((target or '').lower())}'>{html.escape(target or '-')}</td>"
                f"<td data-sort='{html.escape(finding.component.category.lower())}'>{html.escape(finding.component.category)}</td>"
                f"<td data-sort='{html.escape(finding.reason.lower())}'>{html.escape(finding.reason)}</td>"
                f"<td data-sort='{html.escape(finding.recommendation.lower())}'>{html.escape(finding.recommendation)}</td>"
                f"<td data-sort='{html.escape(', '.join(finding.component.evidence[:5]).lower())}'>{html.escape(', '.join(finding.component.evidence[:5]))}</td>"
                "</tr>"
            )
        status_data = [
            {"key": "green", "label": "Green", "value": counts["green"], "color": "#2ca85e"},
            {"key": "amber", "label": "Amber", "value": counts["amber"], "color": "#f2a93b"},
            {"key": "yellow", "label": "Yellow", "value": counts["yellow"], "color": "#e1c627"},
            {"key": "red", "label": "Red", "value": counts["red"], "color": "#df4052"},
            {"key": "grey", "label": "Grey", "value": counts["grey"], "color": "#7c8797"},
        ]
        legend = "".join(
            (
                f"<button type='button' class='legend-item' data-filter='{item['key']}'>"
                f"<span style='background:{item['color']}'></span>"
                f"{item['label']} <strong>{item['value']}</strong></button>"
            )
            for item in status_data
        )
        styles = """
body{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:#f4f7fb;color:#172033}
main{max-width:1500px;margin:32px auto;padding:0 24px} h1{margin-bottom:6px}
.meta{color:#526075}.summary-grid{display:grid;grid-template-columns:minmax(520px,1.45fr) minmax(360px,.75fr);gap:18px;margin:24px 0}
.cards{display:grid;grid-template-columns:repeat(3,minmax(110px,1fr));gap:12px}
.card,.chart-card{background:#fff;border:1px solid #dfe6ef;border-radius:12px;padding:16px;box-shadow:0 3px 12px #20305010}
.card strong{display:block;font-size:25px;margin-top:5px}.chart-card{position:relative;min-height:290px}
.chart-card h2{font-size:17px;margin:0 0 4px}.chart-help{font-size:12px;color:#647188;margin:0 0 8px}
#status-pie{display:block;width:100%;height:190px;cursor:pointer}.chart-tooltip{position:absolute;display:none;pointer-events:none;background:#172033;color:#fff;padding:7px 9px;border-radius:7px;font-size:12px;box-shadow:0 4px 14px #0003}
.legend{display:flex;gap:7px;flex-wrap:wrap}.legend-item{border:1px solid #dbe3ed;background:#fff;border-radius:16px;padding:5px 9px;cursor:pointer;color:#263249}
.legend-item span{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}.legend-item.active{outline:2px solid #2e68c7;background:#eef5ff}
.table-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:8px 0}.filter-state{color:#526075;font-size:13px}
.clear-filter{border:1px solid #b9c7d8;background:#fff;border-radius:7px;padding:7px 10px;cursor:pointer}
table{width:100%;border-collapse:collapse;background:#fff}th,td{border:1px solid #dfe6ef;padding:10px;text-align:left;vertical-align:top;font-size:13px}
th{background:#eaf0f8;position:sticky;top:0;z-index:1}.sortable{cursor:pointer;user-select:none;padding-right:24px;position:relative}
.sortable::after{content:'↕';position:absolute;right:8px;color:#718099}.sortable[aria-sort='ascending']::after{content:'↑';color:#1e5fb8}.sortable[aria-sort='descending']::after{content:'↓';color:#1e5fb8}
.sortable:focus{outline:3px solid #6aa4ef;outline-offset:-3px}.badge{font-weight:700;padding:4px 8px;border-radius:14px}
.green{background:#d7f5df;color:#17652c}.amber{background:#ffe5bd;color:#7a4500}.yellow{background:#fff4ad;color:#5f5200}
.red{background:#ffd7dc;color:#861d2a}.grey{background:#e4e8ee;color:#46505e}tr[hidden]{display:none}
@media(max-width:1000px){.summary-grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(3,1fr)}.table-wrap{overflow:auto}}
@media(max-width:650px){.cards{grid-template-columns:repeat(2,1fr)}}
"""
        script = """
(() => {
  const statusData = JSON.parse(document.getElementById('status-data').textContent);
  const table = document.getElementById('findings-table');
  const tbody = table.tBodies[0];
  const headers = [...table.querySelectorAll('th.sortable')];
  const statusRank = {red: 0, grey: 1, amber: 2, yellow: 3, green: 4};
  let activeFilter = null;

  function sortTable(column, direction) {
    const rows = [...tbody.rows];
    rows.sort((left, right) => {
      let a = left.cells[column].dataset.sort || left.cells[column].textContent.trim();
      let b = right.cells[column].dataset.sort || right.cells[column].textContent.trim();
      if (column === 0) {
        a = statusRank[a] ?? 99;
        b = statusRank[b] ?? 99;
        return direction === 'ascending' ? a - b : b - a;
      }
      return direction === 'ascending'
        ? a.localeCompare(b, undefined, {numeric: true, sensitivity: 'base'})
        : b.localeCompare(a, undefined, {numeric: true, sensitivity: 'base'});
    });
    rows.forEach(row => tbody.appendChild(row));
    headers.forEach(header => header.setAttribute('aria-sort', 'none'));
    headers[column].setAttribute('aria-sort', direction);
  }

  headers.forEach((header, column) => {
    const activate = () => {
      const direction = header.getAttribute('aria-sort') === 'ascending'
        ? 'descending' : 'ascending';
      sortTable(column, direction);
    };
    header.addEventListener('click', activate);
    header.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        activate();
      }
    });
  });

  function applyFilter(status) {
    activeFilter = activeFilter === status ? null : status;
    [...tbody.rows].forEach(row => {
      row.hidden = Boolean(activeFilter && row.dataset.status !== activeFilter);
    });
    document.querySelectorAll('.legend-item').forEach(button => {
      button.classList.toggle('active', button.dataset.filter === activeFilter);
    });
    const visible = [...tbody.rows].filter(row => !row.hidden).length;
    document.getElementById('filter-state').textContent = activeFilter
      ? `Showing ${visible} ${activeFilter.toUpperCase()} findings`
      : `Showing all ${visible} findings`;
  }
  document.querySelectorAll('.legend-item').forEach(button => {
    button.addEventListener('click', () => applyFilter(button.dataset.filter));
  });
  document.getElementById('clear-filter').addEventListener('click', () => {
    if (activeFilter) applyFilter(activeFilter);
  });

  const canvas = document.getElementById('status-pie');
  const context = canvas.getContext('2d');
  const tooltip = document.getElementById('chart-tooltip');
  const total = statusData.reduce((sum, item) => sum + item.value, 0);
  let hoverIndex = -1;
  let animationProgress = 0;

  function dimensions() {
    return {x: canvas.width / 2, y: canvas.height / 2, radius: Math.min(canvas.width, canvas.height) * 0.34};
  }
  function draw(progress) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    const {x, y, radius} = dimensions();
    let start = -Math.PI / 2;
    statusData.forEach((item, index) => {
      const sweep = total ? (Math.PI * 2 * item.value / total) * progress : 0;
      const currentRadius = radius + (index === hoverIndex ? 7 : 0);
      context.beginPath();
      context.moveTo(x, y);
      context.arc(x, y, currentRadius, start, start + sweep);
      context.closePath();
      context.fillStyle = item.color;
      context.fill();
      context.strokeStyle = '#fff';
      context.lineWidth = 3;
      context.stroke();
      start += sweep;
    });
    context.beginPath();
    context.arc(x, y, radius * 0.48, 0, Math.PI * 2);
    context.fillStyle = '#fff';
    context.fill();
    context.fillStyle = '#172033';
    context.textAlign = 'center';
    context.font = '700 25px Segoe UI,Arial';
    context.fillText(String(total), x, y + 4);
    context.font = '12px Segoe UI,Arial';
    context.fillStyle = '#637087';
    context.fillText('findings', x, y + 23);
  }
  const startedAt = performance.now();
  function animate(now) {
    animationProgress = Math.min(1, (now - startedAt) / 900);
    draw(1 - Math.pow(1 - animationProgress, 3));
    if (animationProgress < 1) requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);

  function segmentAt(event) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const pointX = (event.clientX - rect.left) * scaleX;
    const pointY = (event.clientY - rect.top) * scaleY;
    const {x, y, radius} = dimensions();
    if (Math.hypot(pointX - x, pointY - y) > radius + 10) return -1;
    let angle = Math.atan2(pointY - y, pointX - x) + Math.PI / 2;
    if (angle < 0) angle += Math.PI * 2;
    let boundary = 0;
    for (let index = 0; index < statusData.length; index += 1) {
      boundary += total ? Math.PI * 2 * statusData[index].value / total : 0;
      if (angle <= boundary && statusData[index].value > 0) return index;
    }
    return -1;
  }
  canvas.addEventListener('mousemove', event => {
    hoverIndex = segmentAt(event);
    draw(1);
    if (hoverIndex < 0) {
      tooltip.style.display = 'none';
      return;
    }
    const item = statusData[hoverIndex];
    const percent = total ? (100 * item.value / total).toFixed(1) : '0.0';
    tooltip.textContent = `${item.label}: ${item.value} (${percent}%) — click to filter`;
    tooltip.style.display = 'block';
    tooltip.style.left = `${event.offsetX + 18}px`;
    tooltip.style.top = `${event.offsetY + 42}px`;
  });
  canvas.addEventListener('mouseleave', () => {
    hoverIndex = -1;
    tooltip.style.display = 'none';
    draw(1);
  });
  canvas.addEventListener('click', event => {
    const index = segmentAt(event);
    if (index >= 0) applyFilter(statusData[index].key);
  });
})();
"""
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Framework Governance Assessment</title>
<style>{styles}</style></head><body><main>
<h1>Framework Governance Assessment</h1>
<div class="meta">{html.escape(assessment.scan.repository)} · {html.escape(assessment.assessed_at)} · Policy {html.escape(assessment.policy_version)}</div>
<section class="summary-grid"><div class="cards">
<div class="card">Compliance<strong>{assessment.compliance_score()}%</strong></div>
<div class="card">Green<strong>{counts['green']}</strong></div>
<div class="card">Amber<strong>{counts['amber']}</strong></div>
<div class="card">Yellow<strong>{counts['yellow']}</strong></div>
<div class="card">Red<strong>{counts['red']}</strong></div>
<div class="card">Grey<strong>{counts['grey']}</strong></div>
</div><section class="chart-card" aria-labelledby="chart-title">
<h2 id="chart-title">Finding distribution</h2>
<p class="chart-help">Hover for details. Click a slice or legend item to filter the table.</p>
<canvas id="status-pie" width="520" height="230" aria-label="Animated finding status pie chart"></canvas>
<div id="chart-tooltip" class="chart-tooltip" role="status"></div>
<div class="legend">{legend}</div>
</section></section>
<div class="table-toolbar"><div id="filter-state" class="filter-state">Showing all {len(rows)} findings</div>
<button type="button" id="clear-filter" class="clear-filter">Show all findings</button></div>
<div class="table-wrap"><table id="findings-table"><thead><tr>
<th class="sortable" tabindex="0" aria-sort="none">Status</th>
<th class="sortable" tabindex="0" aria-sort="none">Component</th>
<th class="sortable" tabindex="0" aria-sort="none">Detected</th>
<th class="sortable" tabindex="0" aria-sort="none">SCAS/Target</th>
<th class="sortable" tabindex="0" aria-sort="none">Category</th>
<th class="sortable" tabindex="0" aria-sort="none">Reason</th>
<th class="sortable" tabindex="0" aria-sort="none">Recommendation</th>
<th class="sortable" tabindex="0" aria-sort="none">Evidence</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<script id="status-data" type="application/json">{json.dumps(status_data)}</script>
<script>{script}</script>
</main></body></html>"""

    @staticmethod
    def _csv(assessment: Assessment, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["status", "component", "detected_version", "ecosystem", "category",
                 "scas_version", "recommended_version", "reason", "recommendation",
                 "policy_rule", "evidence"]
            )
            for finding in assessment.findings:
                record = finding.catalog_record
                writer.writerow(
                    [
                        finding.status.value,
                        finding.component.name,
                        finding.component.version or "",
                        finding.component.ecosystem,
                        finding.component.category,
                        record.version if record else "",
                        record.recommended_version if record else "",
                        finding.reason,
                        finding.recommendation,
                        finding.policy_rule,
                        "; ".join(finding.component.evidence),
                    ]
                )

    @staticmethod
    def _cyclonedx(assessment: Assessment) -> dict:
        components = []
        for component in assessment.scan.components:
            item = {
                "type": "framework" if component.category == "framework" else "library",
                "name": component.name,
                "version": component.version or "unknown",
                "properties": [
                    {"name": "governance:ecosystem", "value": component.ecosystem},
                    {"name": "governance:category", "value": component.category},
                    {"name": "governance:confidence", "value": str(component.confidence)},
                ],
            }
            if component.purl:
                item["purl"] = component.purl
            components.append(item)
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {"timestamp": assessment.assessed_at},
            "components": components,
        }


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
