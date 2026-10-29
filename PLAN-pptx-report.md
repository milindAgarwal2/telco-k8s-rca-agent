# Plan: per-incident PPTX report (on demand) + size impact

## Can we do it? Yes — and the template maps cleanly onto incident data.

The uploaded `RCA full report template.pptx` is Ericsson's standard RCA deck,
3 slides:
1. **RCA problem definition** — What / Where / When, RCA driver & responsible,
   Goal, Significance.
2. **Sequence of events** — a swimlane timeline (actors as lanes, timestamped
   events along an hour scale).
3. Example-filled version of slide 2.

An incident already carries almost everything these slides want:

| Template field | Incident source |
|----------------|-----------------|
| What happened? | `symptom` + top hypothesis `cause` |
| Where? | `affected_resource`, `namespace`, workload/service (`graph.owners`) |
| When? | `detected_at` + each change's precise `managedFields` time |
| Significance | severity, `blast_radius` (downstream impact), correlated count |
| Sequence of events (swimlanes) | the **change-attribution timeline** we added in 0.5.1 — each change has an actor (human/automation) and a timestamp, which is exactly "lane = actor, event = timestamped change". Plus fault events (OOMKilled, etc.) with their times. |
| Analysis / root cause | ranked hypotheses + evidence chain + citations |
| Suggested next steps | `suggested_next_steps` (runbook hits) |

So the deck isn't a stretch — it's a re-rendering of the same evidence the
incident report already holds, in Ericsson's slide layout.

---

## Size impact (measured, not estimated)

Generating PPTX needs `python-pptx`, which pulls in:

| Package | Installed | Note |
|---------|-----------|------|
| Pillow | ~22 MB | image handling (for logos/graph snapshot) |
| lxml | ~12 MB | XML (OOXML) writing |
| python-pptx | ~2.5 MB | the library itself |
| XlsxWriter | ~1.7 MB | pulled in by python-pptx (chart data) |
| **Total new** | **~38 MB installed** | |

**Compressed Docker-layer / package delta: ~14 MB** (measured by gzipping the
new packages).

So the Cobra package goes from **~90 MB → ~104 MB** (+~14 MB, +~15%). The image
stays well under the pre-0.5.0 Streamlit-era size (216 MB). No pyarrow/pandas —
this is a modest, targeted addition.

**Options to control the cost:**
- **(A) Accept +14 MB, bundle always** — simplest; feature always available.
  Recommended unless you want to stay minimal.
- **(B) Optional `pptx` extra, built into the Cobra image** — `python-pptx`
  goes in a `[pptx]` extra; the Cobra Dockerfile installs it, other builds can
  skip it. Same +14 MB on the deployed image, but keeps a "core" build lean.
- **(C) Lazy/soft dependency** — code imports `python-pptx` only inside the
  export function; if not installed, the "Download PPTX" button shows a tooltip
  "PPTX export not installed in this build". Lets ONE image serve both
  (feature present only if the extra was installed). Pairs well with (B).

Recommendation: **(A)** if +14 MB is acceptable (it keeps things simple and the
feature always works), otherwise **(B)+(C)**.

---

## Implementation plan

### 1. Generator module — `webhook/pptx_report.py`
- `build_incident_pptx(report, owners) -> bytes`: opens the template
  `RCA full report template.pptx` as a starting point (python-pptx can load and
  edit an existing deck, preserving Ericsson styling/branding), then fills it:
  - **Slide 1 (problem definition):** replace the `<...>` placeholders with
    `symptom`, `affected_resource`/`namespace`/workload/service (Where),
    `detected_at` (When), severity + blast radius (Significance), top cause +
    confidence (What).
  - **Slide 2 (sequence of events):** build swimlanes from the incident's
    timeline — one lane per distinct actor found in the change citations
    (e.g. "kubectl (human)", "Helm", "argocd"), plus a "cluster/kubelet" lane
    for fault events (OOMKilled/CrashLoop). Each event is placed by its
    timestamp. Reuse the template's timeline shapes where practical; otherwise
    add text boxes positioned by time.
  - Append an **analysis slide**: ranked hypotheses (cause, confidence bar as a
    shape), evidence chain, citations, and suggested next steps.
- Ship the template file inside the package (it's already in the repo root;
  move a copy to `webhook/templates_pptx/` and add to `package-data`, ~430 KB).
- Pure in-memory: returns bytes; no temp files on the read-only root FS.

### 2. Endpoint — `GET /ui/incidents/{id}/pptx`
- Looks up the incident, builds the deck, returns it as a download:
  `media_type=application/vnd.openxmlformats-officedocument.presentationml.presentation`,
  `Content-Disposition: attachment; filename=RCA-<incident_id>.pptx`.
- Read-only: it only reads the already-gathered incident + graph; no cluster
  mutation, no new RBAC.
- Generated **on demand only** (your requirement — "only when selected"):
  nothing is produced until the user clicks, so no cost per incident otherwise.

### 3. UI — a button in the incident detail panel
- Add a **"⬇️ Download RCA PPTX"** button at the top of the detail panel
  (`_incident_detail.html`), linking to the endpoint. (With option C, the
  button is disabled with a tooltip when the lib isn't installed.)

### 4. Packaging / deps
- Add `python-pptx>=0.6.23` (either to core deps for option A, or a `[pptx]`
  extra for B). Add the template to `package-data`. Dockerfile install line
  updated accordingly.
- Bump version (**0.6.0** — this is a feature, though not an architectural
  change; or 0.5.3 if you prefer to keep it in the 0.5.x fix line). Your call.

### 5. Tests
- `build_incident_pptx` on a sample report returns non-empty bytes that
  `python-pptx` can re-open and whose slides contain the incident's symptom,
  resource, and at least one hypothesis/actor — a round-trip test, no cluster.
- Endpoint returns 200 + the correct content-type and filename.

**Effort: moderate (template placeholder-filling + swimlane positioning is the
fiddly part). Risk: low — isolated module + endpoint, on-demand only, soft-
importable so it can't break the core service.**

---

## Open choices for you
1. **Size tradeoff:** (A) always bundle (+14 MB, simplest) — **my default** —
   vs (B)+(C) optional extra + soft import.
2. **Swimlane fidelity:** faithfully reuse the template's timeline shapes
   (more effort, pixel-matches the sample) vs. generate a clean timeline slide
   in the same style (less fiddly, still on-brand). I'd start with the latter
   and tighten if you want an exact match.
3. **Version:** 0.6.0 (feature) vs 0.5.3 (keep in fix line).

Tell me the three and I'll build it; silent = (A), clean-timeline, 0.6.0.
