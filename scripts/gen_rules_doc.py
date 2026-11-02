"""Generate presentation collateral for the "rules-first reasoning" story:

  * docs/reasoning-rules.docx  -- a reference document of every deterministic
    rule the extractive pipeline applies (scoring weights, detectors, windows).
  * docs/reasoning-rules.pptx  -- a single summary slide for the deck.

All rules/weights/thresholds below are transcribed from the actual code
(src/rca_agent/reasoning/steps.py + config.py) as of version 0.8.2. If the
code changes, re-run this script.

    .venv/bin/python scripts/gen_rules_doc.py
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PColor
from pptx.util import Inches
from pptx.util import Pt as PPt

OUT = Path(__file__).resolve().parent.parent / "docs"
NAVY = RGBColor(0x1F, 0x3A, 0x6B)
BLUE = RGBColor(0x3B, 0x6F, 0xD4)

# ---- The verified rule set (from steps.py @ 0.8.2) -------------------------

SCORING = [
    ("+0.50", "Readiness/liveness probe failure",
     ("Pod is Running but failing its probe (e.g. 'Readiness probe failed ... HTTP 500'). "
     "The app is up but unhealthy -- a strong, self-contained fault.")),
    ("+0.45", "Fault event on the resource or upstream",
     ("A terminal fault reason seen in events/pod status: OOMKilled, CrashLoopBackOff, "
     "ImagePullBackOff, ErrImagePull, or Evicted.")),
    ("+0.30", "Recent change correlated in time AND consumed by the pod",
     ("A ConfigMap/Secret the affected pod actually mounts, or a rollout/scaling that names "
     "the resource, within the 15-minute correlation window.")),
    ("+0.20", "Unhealthy upstream dependency (cascade)",
     ("A dependency the resource calls (from the graph's 'calls' edges) is itself unhealthy; "
     "models 'SMF errors <- UPF unreachable'.")),
    ("+0.15", "Error/fatal log lines",
     "Weak supporting signal: tail of pod logs contains 'error' or 'fatal' lines."),
    ("+0.05", "Uncorrelated recent change",
     ("A change NOT mounted by the affected pod -- kept but weighted so low it cannot "
     "outrank a real fault.")),
]

DETECTORS = [
    ("Fault-event detector",
     ("Scans evidence for the terminal fault reasons (OOMKilled / CrashLoopBackOff / "
     "ImagePullBackOff / ErrImagePull / Evicted). Each creates a 'fault' hypothesis.")),
    ("Probe-failure detector (_detect_probe_failure)",
     ("Prefers an 'Unhealthy' event mentioning a readiness/liveness probe; falls back to a "
     "pod 'not ready' status that has NO terminal fault reason (so it never double-counts "
     "an OOMKill as a probe failure).")),
    ("Change correlation (change_correlation)",
     ("Lists changes in the last 15 min. Config/Secret edits are kept ONLY if the pod mounts "
     "that object (read from graph 'mounts' edges); rollouts are kept if they name the "
     "resource. No mount info -> keep but mark uncorrelated (weak).")),
    ("Graph walk (graph_walk)",
     ("Upstream unhealthy nodes = candidate causes; downstream nodes = blast radius. "
     "Walks the service anchor AND its pods, unioning results.")),
    ("Concrete-failure label (_concrete_failure_label)",
     ("Resolves the real error term (e.g. ImagePullBackOff) so a change headline reads "
     "'recent rollout -> ImagePullBackOff', and the runbook query is enriched (0.8.2).")),
    ("Change->fault linking (_link_change_to_fault)",
     ("If a CORRELATED change and a fault both reference the pod, chain them into one causal "
     "story (the headline 'ConfigMap memory-limit change -> OOMKilled').")),
]

POST = [
    "Confidence is clamped to a maximum of 0.99 (never claims certainty).",
    "Every hypothesis must be tied to evidence; anything unsupported is never created.",
    "The symptom ('<alert> on <resource>') is inserted at the head of every evidence chain.",
    "Hypotheses are sorted by confidence, highest first (top-2 is what the report leads with).",
]

PRINCIPLES = [
    ("Rules first, LLM second",
     ("Deterministic code gathers evidence and generates + scores the candidate causes. "
     "The LLM (optional) only reorders and explains the existing candidates -- it cannot "
     "invent a cause. Default mode is extractive (no LLM).")),
    ("Evidence-bound",
     ("A hypothesis only exists if real evidence created it; confidence is the sum of the "
     "matched rule weights above.")),
    ("Reproducible",
     "Same inputs -> same ranking. No randomness, no external calls in the default path."),
]

EXAMPLES = [
    ("ImagePullBackOff (your demo)",
     ("Event 'ImagePullBackOff' on the pod -> fault rule (+0.45). Pod also not-ready, but the "
     "terminal reason is present so it's scored as a fault, not a probe failure. "
     "Top hypothesis: '<pod> ImagePullBackOff', confidence ~0.45-0.60.")),
    ("Readiness probe failing (real cSAEGW-C pod)",
     ("Event 'Unhealthy: Readiness probe failed ... HTTP 500', no terminal reason -> probe "
     "rule (+0.50). Top hypothesis: '<pod> failing health probe (readiness probe failed 500)'.")),
    ("ConfigMap change -> OOMKilled (the canonical chain)",
     ("OOMKilled fault (+0.45) + a correlated ConfigMap memory-limit edit the pod mounts "
     "(+0.30), linked into one chain: 'symptom <- OOMKilled <- memory limit lowered in "
     "ConfigMap at 14:02'. Confidence ~0.75.")),
    ("Upstream cascade",
     ("Pod healthy-ish but an upstream service it calls is unhealthy (+0.20): "
     "'<upstream> unhealthy (cascades to <pod>)' appears as a lower-ranked contributing cause.")),
]


def build_docx() -> Path:
    d = Document()

    h = d.add_heading("RCA Agent — Rules-First Reasoning", level=0)
    h.runs[0].font.color.rgb = NAVY
    sub = d.add_paragraph("How the agent decides the root cause before any LLM is involved "
                          "(extractive pipeline, version 0.8.2)")
    sub.runs[0].italic = True

    d.add_heading("What 'rules-first' means", level=1)
    for title, body in PRINCIPLES:
        p = d.add_paragraph(style="List Bullet")
        r = p.add_run(f"{title}: "); r.bold = True
        p.add_run(body)

    d.add_heading("Scoring rules (confidence = sum of matched weights)", level=1)
    t = d.add_table(rows=1, cols=3)
    t.style = "Light Grid Accent 1"
    hdr = t.rows[0].cells
    for i, label in enumerate(("Weight", "Rule", "What triggers it")):
        hdr[i].paragraphs[0].add_run(label).bold = True
    for w, rule, desc in SCORING:
        row = t.add_row().cells
        row[0].paragraphs[0].add_run(w).bold = True
        row[1].text = rule
        row[2].text = desc

    d.add_heading("Detectors (deterministic signal extraction)", level=1)
    for name, body in DETECTORS:
        p = d.add_paragraph(style="List Bullet")
        r = p.add_run(f"{name} — "); r.bold = True
        p.add_run(body)

    d.add_heading("Post-processing & guardrails", level=1)
    for line in POST:
        d.add_paragraph(line, style="List Bullet")

    d.add_heading("Worked examples", level=1)
    for title, body in EXAMPLES:
        p = d.add_paragraph(style="List Bullet")
        r = p.add_run(f"{title}: "); r.bold = True
        p.add_run(body)

    d.add_heading("Tunable windows & thresholds (config.py defaults)", level=1)
    for line in (
        "Change-correlation window: 15 minutes (change_correlation_window_minutes)",
        "Recent-events lookback: 30 minutes (gather_evidence)",
        "Log tail scanned for error/fatal: 200 lines (log_tail_lines)",
        "Event-watch poll interval: 15 seconds; graph rebuild: 60 seconds",
        "Runbook hits returned: top 3 (runbook_rag_top_k)",
        "Default reasoning_mode: extractive (LLM off unless set to 'llm')",
    ):
        d.add_paragraph(line, style="List Bullet")

    note = d.add_paragraph()
    nr = note.add_run("All weights, reasons and thresholds above are transcribed directly "
                      "from src/rca_agent/reasoning/steps.py and config.py at version 0.8.2.")
    nr.italic = True; nr.font.size = Pt(9); nr.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    out = OUT / "reasoning-rules.docx"
    d.save(str(out))
    return out


def build_pptx() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Title
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.3), Inches(1.0))
    tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.text = "Rules-First Reasoning"
    p.runs[0].font.size = PPt(34); p.runs[0].font.bold = True
    p.runs[0].font.color.rgb = PColor(0x1F, 0x3A, 0x6B)
    sp = tf.add_paragraph()
    sp.text = "Deterministic code finds & scores the cause. The LLM only reorders + explains (optional)."
    sp.runs[0].font.size = PPt(15); sp.runs[0].font.italic = True
    sp.runs[0].font.color.rgb = PColor(0x55, 0x55, 0x55)

    # Left column: scoring weights
    left = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(6.3), Inches(5.6))
    lf = left.text_frame; lf.word_wrap = True
    head = lf.paragraphs[0]; head.text = "Scoring rules (confidence = sum of weights)"
    head.runs[0].font.size = PPt(18); head.runs[0].font.bold = True
    head.runs[0].font.color.rgb = PColor(0x3B, 0x6F, 0xD4)
    for w, rule, _desc in SCORING:
        para = lf.add_paragraph()
        r1 = para.add_run(); r1.text = f"{w}  "; r1.font.bold = True
        r1.font.color.rgb = PColor(0x2E, 0x7D, 0x32); r1.font.size = PPt(15)
        r2 = para.add_run(); r2.text = rule; r2.font.size = PPt(15)
        para.space_after = PPt(6)

    # Right column: detectors + guardrails
    right = slide.shapes.add_textbox(Inches(7.0), Inches(1.5), Inches(5.9), Inches(5.6))
    rf = right.text_frame; rf.word_wrap = True
    h2 = rf.paragraphs[0]; h2.text = "Detectors"
    h2.runs[0].font.size = PPt(18); h2.runs[0].font.bold = True
    h2.runs[0].font.color.rgb = PColor(0x3B, 0x6F, 0xD4)
    for name, _body in DETECTORS:
        para = rf.add_paragraph(); para.text = f"• {name.split('(')[0].strip()}"
        para.runs[0].font.size = PPt(14); para.space_after = PPt(3)
    h3 = rf.add_paragraph(); h3.text = "Guardrails"
    h3.runs[0].font.size = PPt(18); h3.runs[0].font.bold = True
    h3.runs[0].font.color.rgb = PColor(0x3B, 0x6F, 0xD4)
    for line in ("Confidence clamped to 0.99 (never certain)",
                 "No evidence -> no hypothesis",
                 "Reproducible: same inputs, same ranking",
                 "Extractive is the default (LLM optional)"):
        para = rf.add_paragraph(); para.text = f"• {line}"
        para.runs[0].font.size = PPt(14); para.space_after = PPt(3)

    out = OUT / "reasoning-rules.pptx"
    prs.save(str(out))
    return out


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    print("wrote", build_docx())
    print("wrote", build_pptx())
