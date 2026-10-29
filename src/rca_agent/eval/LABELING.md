# Incident capture & labeling guide

How to collect real incidents from a running agent and label them later so they
become ground-truth data for precision/recall evaluation.

This captures data NOW (safe, off by default) so the labeling and precision/
recall scoring can happen LATER without re-running anything live.

---

## 1. Turning capture ON

Capture is controlled at **deploy time by environment variables** (the `RCA_*`
pattern), NOT from the dashboard. This is deliberate: starting to write
potentially-sensitive production log data to disk is an operational decision,
not something a dashboard viewer should toggle, and an env var survives in the
deploy config instead of being lost on redeploy.

| Env var | Default | Meaning |
|---|---|---|
| `RCA_INCIDENT_CAPTURE_PATH` | *(empty = OFF)* | Set to a writable JSONL file to enable, e.g. `/data/captures/incidents.jsonl` |
| `RCA_INCIDENT_CAPTURE_REDACT_LOGS` | `false` | Drop raw log bodies (keep reasons/timestamps) — use if logs may hold sensitive data |
| `RCA_INCIDENT_CAPTURE_INCLUDE_GRAPH` | `true` | Include a graph-neighborhood snapshot (needed for full replay) |
| `RCA_INCIDENT_CAPTURE_MAX_RECORDS` | `5000` | Rolling cap; oldest records drop past this |
| `RCA_INCIDENT_CAPTURE_GRAPH_RADIUS` | `2` | Neighborhood radius for the snapshot |

On Cobra, mount a volume and point the var at it (so records survive container
restarts), e.g. add to the `docker run` in `deploy-cobra.sh`:

```bash
-e RCA_INCIDENT_CAPTURE_PATH=/data/captures/incidents.jsonl \
-e RCA_INCIDENT_CAPTURE_REDACT_LOGS=true \
-v /home/eagamil/rca-captures:/data/captures \
```

Then every incident (auto-detected OR webhook-posted) appends one JSONL line.
Nothing else changes; capture is best-effort and never breaks detection.

> **The capture file is SENSITIVE** — it contains log lines and object names
> from the monitored namespace. Keep it on a restricted volume; never commit it
> to git. Use `REDACT_LOGS=true` if in doubt.

### Is there a GUI switch?
No control in the GUI by design (see above). A future read-only *status*
indicator on the Health tab ("capture: on, N records") is a reasonable
nice-to-have, but the on/off stays in config.

---

## 2. The record schema (what gets captured)

One JSON object per line (`eval/capture.py::build_record`). Three layers:

```jsonc
{
  "schema_version": "1",
  "incident_id": "...", "captured_at": "...", "source": "event_watcher|webhook",
  "namespace": "...",

  "input": {                     // the REPRODUCIBLE case (replayable offline)
    "symptom": "...",
    "affected_resource": "...", "affected_anchor": "...", "anchor_kind": "...",
    "affected_pods": ["..."],
    "detected_at": "...",
    "evidence": [ /* Evidence[] with category, summary, timestamp, citations */ ],
    "graph_neighborhood": { "nodes": [...], "edges": [...] }
  },

  "output": {                    // what the agent CONCLUDED (to be scored)
    "hypotheses": [ {"cause": "...", "confidence": 0.5,
                     "evidence_chain": [...], "citations": [...]} ],
    "blast_radius": [...], "upstream_unhealthy": [...],
    "status": "active|inactive", "reasoning_mode": "extractive"
  },

  "labels": {                    // EMPTY at capture; a human fills this later
    "status": "unlabeled",       // -> "labeled" | "skipped"
    "gold_causes": [],           // the TRUE root cause(s), as text
    "hypothesis_verdicts": [],   // [{"cause": "...", "verdict": "TP|FP|tolerated"}]
    "is_real_incident": null,    // true | false  (false = agent should stay quiet)
    "labeler": "", "labeled_at": "", "notes": ""
  }
}
```

Why capture `input` and not just the hypotheses: with the evidence + graph
snapshot frozen, each record is a **replayable test case** — you can re-run an
improved pipeline over it and re-score, and judge whether a NEW hypothesis is a
true or false positive. (It also doubles as an "as-of fault" snapshot, assessment
point #7.)

---

## 3. The labeling process (done later)

Prerequisite: a few dozen captured records from a real deployment.

For each record, the labeler fills the `labels` block:

1. **Decide `is_real_incident`.** Was this a genuine fault, or noise the agent
   should not have raised? `false` here is how we measure precision on
   "staying quiet."
2. **Fill `gold_causes`** — the COMPLETE set of true root cause(s), in the same
   style as the hypothesis `cause` text (e.g. `"upf-0 OOMKilled"`,
   `"service/eric-pc-kvdb-rd-server unhealthy"`). Multiple entries for a
   multi-fault incident. This is the single most important field.
3. **Give each emitted hypothesis a verdict** in `hypothesis_verdicts`:
   - `TP` — matches a gold cause (correct),
   - `FP` — a claimed cause that is NOT real (spurious),
   - `tolerated` — a legitimate low-value co-hypothesis we don't penalise
     (e.g. the generic "failing health probe" that always accompanies the real
     cause). **Write the tolerated-vs-FP policy down once and apply it
     consistently** — this policy decision IS the hard part of labeling.
4. Set `status: "labeled"`, `labeler`, `labeled_at`, and any `notes`
   (especially when the correct cause was NOT in the agent's output at all —
   that is a false negative and the most useful signal for improving the agent).

Mechanically, labeling = editing the JSONL (or a copy). It can be done in a text
editor, a notebook, or a small future UI. Keep labeled files separate from raw
captures.

### How labels become precision/recall
Once `gold_causes` + `hypothesis_verdicts` are filled, the (future) scorer
computes, per record and aggregated:

- **TP** = agent hypotheses matching a gold cause
- **FP** = agent hypotheses marked FP (spurious)
- **FN** = gold causes with no matching agent hypothesis
- **precision = TP / (TP + FP)**, **recall = TP / (TP + FN)**

`tolerated` hypotheses are excluded from FP. Records with
`is_real_incident=false` feed a "stay quiet" precision check (any raised
hypothesis is a FP).

Labeled records can also be adapted into `eval.FaultCase`s (via their `input`
block) so they join the automated harness — turning real Cobra incidents into
permanent regression tests.

---

## 4. Who should label

Best → acceptable:

1. **The SRE / network engineer who operated the cluster during the incident**
   — they know the actual root cause (what they found and fixed). Highest-
   quality `gold_causes`, especially for the hard false-negative cases.
2. **A domain SME for the 5G core (Ericsson PCC / eric-pc-sm etc.)** — can
   judge cascades and dependencies the agent can't see (e.g. "these 6 pods share
   this backend").
3. **The agent's developer** — can label the mechanical cases (OOMKilled,
   ImagePull) reliably, but should NOT self-judge the ambiguous
   tolerated-vs-FP calls alone (risk of grading to the agent's behaviour rather
   than the truth). Pair with #1/#2 for those.

Practical model: the developer sets up the labeling file and the FP/tolerated
policy; an SRE/SME does the actual `gold_causes` judgments; disagreements get a
`notes` entry and a second opinion. Even 20-30 well-labeled real incidents give
meaningful precision/recall — volume helps confidence, not correctness.
