"""Per-incident RCA report deck (PPTX), generated on demand.

Mirrors the structure of the Ericsson "RCA full report template.pptx"
(problem definition -> sequence of events -> analysis), filled from an
:class:`~rca_agent.models.incident.IncidentReport`. Generated only when the
user clicks "Download RCA PPTX" in the incident detail (GET
/ui/incidents/{id}/pptx) -- nothing is produced per incident otherwise.

``python-pptx`` is imported lazily so the core service runs without it; the
endpoint returns a clear message if the ``[pptx]`` extra isn't installed.
Returns bytes (in-memory) -- no temp files, safe on a read-only root FS.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

# Ericsson-ish accent; kept simple and on-brand without copying template assets.
_BLUE = (0x1E, 0x88, 0xE5)
_DARK = (0x22, 0x22, 0x22)
_GREY = (0x66, 0x66, 0x66)
_RED = (0xC6, 0x28, 0x28)
_AMBER = (0xB0, 0x71, 0x00)


def pptx_available() -> bool:
    try:
        import pptx  # noqa: F401
        return True
    except ImportError:
        return False


def _ts(value) -> str:
    if not value:
        return ""
    return str(value)[:19].replace("T", " ")


def build_incident_pptx(report, owners: dict | None = None) -> bytes:
    """Build the RCA deck for ``report`` and return it as PPTX bytes.

    Raises RuntimeError if python-pptx is not installed.
    """
    try:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.util import Inches, Pt
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "python-pptx is not installed. Install the pptx extra: pip install '.[pptx]'"
        ) from exc

    owners = owners or {}
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    def rgb(c):
        return RGBColor(*c)

    def add_title(slide, text, sub=None):
        tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.3), Inches(0.9))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.text = text
        r = tf.paragraphs[0].runs[0]
        r.font.size = Pt(26); r.font.bold = True; r.font.color.rgb = rgb(_DARK)
        if sub:
            sb = slide.shapes.add_textbox(Inches(0.5), Inches(1.05), Inches(12.3), Inches(0.5))
            sf = sb.text_frame; sf.word_wrap = True; sf.text = sub
            sr = sf.paragraphs[0].runs[0]
            sr.font.size = Pt(13); sr.font.italic = True; sr.font.color.rgb = rgb(_GREY)

    def add_field(slide, x, y, w, h, label, value, value_color=_DARK, value_size=14):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame; tf.word_wrap = True
        p = tf.paragraphs[0]
        lr = p.add_run(); lr.text = label + "  "
        lr.font.size = Pt(13); lr.font.bold = True; lr.font.color.rgb = rgb(_BLUE)
        vr = p.add_run(); vr.text = value or "—"
        vr.font.size = Pt(value_size); vr.font.color.rgb = rgb(value_color)
        return box

    sev = getattr(report.severity, "value", report.severity)
    top = report.hypotheses[0] if report.hypotheses else None
    # Service-anchored "Where": lead with the anchor (service/workload), then
    # namespace. Affected pods are listed as their own field below.
    anchor_kind = report.anchor_kind or "pod"
    where = f"{anchor_kind}: {report.affected_anchor or report.affected_resource or 'unknown'}"
    if report.namespace:
        where += f"  ·  namespace: {report.namespace}"

    # ---- Slide 1: RCA problem definition ----
    s1 = prs.slides.add_slide(blank)
    add_title(s1, "RCA problem definition",
              f"Incident {report.incident_id}  ·  generated {_ts(datetime.now(timezone.utc))}")
    y = 1.7
    add_field(s1, 0.6, y, 12.0, 0.6, "What happened?",
              report.symptom + (f"  — likely cause: {top.cause}" if top else ""))
    add_field(s1, 0.6, y + 0.7, 12.0, 0.6, "Where?", where)
    pods_str = ", ".join(report.affected_pods[:8]) if report.affected_pods else "—"
    if report.affected_pods and len(report.affected_pods) > 8:
        pods_str += f"  (+{len(report.affected_pods) - 8} more)"
    add_field(s1, 0.6, y + 1.4, 12.0, 0.6, "Affected pods", pods_str, value_size=12)
    add_field(s1, 0.6, y + 2.1, 12.0, 0.6, "When?",
              f"detected {_ts(report.detected_at) or _ts(report.created_at)}")
    sig = f"Severity: {sev}"
    if report.blast_radius:
        sig += f"  ·  blast radius: {', '.join(report.blast_radius)}"
    if report.related_incidents:
        sig += f"  ·  {len(report.related_incidents)} correlated incident(s)"
    add_field(s1, 0.6, y + 2.8, 12.0, 0.9, "Significance", sig)
    conf = f"{(top.confidence * 100):.0f}% confidence" if top else "n/a"
    add_field(s1, 0.6, y + 3.8, 12.0, 0.6, "Top hypothesis",
              (top.cause if top else "none") + f"  ({conf})",
              value_color=_RED if sev == "critical" else _AMBER)

    # ---- Slide 2: Sequence of events (swimlanes by actor) ----
    s2 = prs.slides.add_slide(blank)
    add_title(s2, "Problem specification — sequence of events",
              "Lanes group events by actor (who); times from Kubernetes events & managedFields.")
    events = _collect_timeline(report)
    if events:
        lanes: dict[str, list] = {}
        for actor, when, label in events:
            lanes.setdefault(actor, []).append((when, label))
        y = 1.8
        lane_h = min(1.4, (5.4 / max(1, len(lanes))))
        for actor, items in lanes.items():
            lbl = s2.shapes.add_textbox(Inches(0.5), Inches(y), Inches(2.6), Inches(lane_h))
            lf = lbl.text_frame; lf.word_wrap = True
            lr = lf.paragraphs[0].add_run(); lr.text = actor
            lr.font.size = Pt(12); lr.font.bold = True; lr.font.color.rgb = rgb(_BLUE)
            ev = s2.shapes.add_textbox(Inches(3.2), Inches(y), Inches(9.6), Inches(lane_h))
            ef = ev.text_frame; ef.word_wrap = True
            for j, (when, label) in enumerate(sorted(items)):
                p = ef.paragraphs[0] if j == 0 else ef.add_paragraph()
                tr = p.add_run(); tr.text = f"{_ts(when)}  "
                tr.font.size = Pt(11); tr.font.bold = True; tr.font.color.rgb = rgb(_DARK)
                mr = p.add_run(); mr.text = label
                mr.font.size = Pt(11); mr.font.color.rgb = rgb(_GREY)
            y += lane_h
    else:
        add_field(s2, 0.6, 2.0, 12.0, 0.6, "Timeline",
                  "No timestamped change/fault events were correlated for this incident.")

    # ---- Slide 3: Analysis — ranked hypotheses & next steps ----
    s3 = prs.slides.add_slide(blank)
    add_title(s3, "Analysis — ranked root-cause hypotheses")
    y = 1.7
    if report.hypotheses:
        for h in report.hypotheses[:4]:
            pct = (h.confidence or 0) * 100
            color = _RED if h.confidence >= 0.75 else (_AMBER if h.confidence >= 0.5 else _BLUE)
            add_field(s3, 0.6, y, 12.0, 0.5, f"{pct:.0f}%", h.cause, value_color=color, value_size=14)
            chain = " → ".join(h.evidence_chain[:4]) if h.evidence_chain else ""
            if chain:
                cb = s3.shapes.add_textbox(Inches(1.2), Inches(y + 0.42), Inches(11.4), Inches(0.5))
                cf = cb.text_frame; cf.word_wrap = True
                crun = cf.paragraphs[0].add_run(); crun.text = chain
                crun.font.size = Pt(10); crun.font.color.rgb = rgb(_GREY)
            y += 1.0
    else:
        add_field(s3, 0.6, y, 12.0, 0.6, "Hypotheses", "none")
        y += 0.9

    sa = getattr(report, "service_area", None)
    if sa is not None and getattr(sa, "mapped", False):
        sa_text = (f"{sa.service_area} (section {sa.section}) — component "
                   f"'{sa.component}': {sa.component_sibling_count} pod(s), "
                   f"service area: {sa.service_area_pod_count} pod(s) "
                   f"[confidence: {sa.confidence}]")
        add_field(s3, 0.6, min(y, 6.3), 12.0, 0.6, "Service area impacted", sa_text)
        y += 0.9

    if report.suggested_next_steps:
        sb = s3.shapes.add_textbox(Inches(0.6), Inches(min(y, 6.3)), Inches(12.0), Inches(0.9))
        sf = sb.text_frame; sf.word_wrap = True
        hr = sf.paragraphs[0].add_run(); hr.text = "Suggested next steps"
        hr.font.size = Pt(13); hr.font.bold = True; hr.font.color.rgb = rgb(_BLUE)
        for step in report.suggested_next_steps[:2]:
            p = sf.add_paragraph(); r = p.add_run(); r.text = step[:300]
            r.font.size = Pt(10); r.font.color.rgb = rgb(_DARK)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _collect_timeline(report) -> list[tuple[str, object, str]]:
    """Build ``(actor_lane, timestamp, label)`` rows from the incident.

    - change citations -> lane = the classified actor source (human/Helm/...)
    - fault/pod_status/event evidence -> lane = "cluster / kubelet"
    """
    rows: list[tuple[str, object, str]] = []
    seen = set()
    for h in report.hypotheses:
        for c in h.citations:
            if c.kind == "change" and c.timestamp:
                lane = c.actor_source or c.actor or "change"
                key = (lane, str(c.timestamp), c.source)
                if key in seen:
                    continue
                seen.add(key)
                rows.append((lane, c.timestamp, f"{c.source}: {c.detail}"))
    for e in report.evidence:
        if e.category in ("pod_status", "event") and e.timestamp:
            key = ("cluster / kubelet", str(e.timestamp), e.summary)
            if key in seen:
                continue
            seen.add(key)
            rows.append(("cluster / kubelet", e.timestamp, e.summary[:80]))
    return rows
