# Plan: node breakdown + graph legend/icons + change attribution

Three requested improvements, each grounded in what the code already exposes.

---

## Request 1 — "1485 nodes" means nothing; show a breakdown by kind

### What exists today
Every graph node already carries a `kind` attribute (`NodeKind`:
`pod`, `service`, `configmap`, `secret`, `pvc`, `deployment`, `replicaset`,
`node`, `network_function`). The metric card just shows the raw total from
`DependencyGraph.stats()`, which only returns `nodes`/`edges`/`changes`/
`last_rebuilt`.

### The fix (small, pure addition)
1. **`dependency_graph.py`** — add `node_breakdown()` returning a count per
   `kind`, e.g. `{"pod": 312, "configmap": 410, "secret": 380, "service": 44,
   "pvc": 150, "deployment": 44, "replicaset": 90, "node": 55}`. Add the same
   dict into `stats()` under a `by_kind` key (backward-compatible — existing
   keys unchanged).
2. **UI `_metrics.html`** — keep the 4 headline cards, but make the **Graph
   nodes** card expandable / add a small breakdown row beneath it:
   `312 pods · 410 configmaps · 380 secrets · 44 services · …`. Rendered from
   `stats.by_kind`, so it auto-updates with the existing 10s metrics poll.
3. Optionally also break down **edges** by `EdgeKind` the same way
   (`calls`/`runs_on`/`mounts`/`managed_by`/`selects`) — cheap, same pattern,
   and equally clarifying ("214 edges" is just as opaque).

### Why this is safe/cheap
Pure read-only counting over the in-memory graph; no new cluster calls, no
schema change, ~15 lines + a template row. Covered by a unit test asserting
the per-kind counts on the demo graph.

**Effort: ~30 min. Risk: negligible.**

---

## Request 2 — different icons per element type + a legend

### What exists today
Nodes are **already shaped by kind** in `visualize.py::_SHAPE`
(pod=`dot`, service=`diamond`, deployment=`triangle`,
replicaset=`triangleDown`, configmap/secret=`box`, pvc=`database`,
node=`square`, nf=`hexagon`). Color currently encodes **health**, not kind.
So the shapes are there — but (a) there's **no legend**, so nobody knows
`diamond = service`, and (b) configmap and secret share the same `box`, and
color carries no kind info, so it's still confusing.

### The fix
1. **Add an on-canvas legend** (the real gap). A small fixed-position box
   (like the existing title label / pod picker) listing each kind with its
   shape glyph + what it means, and the health color key. Built from the
   `_SHAPE` + `_HEALTH_COLOR` maps so it can't drift from the actual render.
2. **Disambiguate configmap vs secret**: give `secret` a distinct shape
   (e.g. `box` → configmap, `database`/`ellipse` → secret, and move pvc to
   something else like `square`-variant), OR keep shapes but add a small
   kind-marker. Simplest: pick unique vis.js shapes per kind so every kind is
   visually distinct. vis.js shapes available: `dot, diamond, triangle,
   triangleDown, square, box, database, hexagon, star, ellipse`.
   Proposed final mapping (all distinct):
   | kind | shape |
   |------|-------|
   | pod | dot |
   | service | diamond |
   | deployment | triangle |
   | replicaset | triangleDown |
   | node (worker) | square |
   | configmap | box |
   | secret | database |
   | pvc | hexagon |
   | network_function | star |
3. **Keep color = health** (green/orange/red/grey) as-is, and say so in the
   legend, so the two encodings (shape=kind, color=health) are explicit and
   non-overlapping.

### Why this is the right shape of fix
The confusion isn't missing shapes — it's missing a key. The legend is the
80% win; the shape de-dup (configmap vs secret) is the other 20%. Both live
entirely in `visualize.py`; no graph/model change.

**Effort: ~45 min. Risk: low (pure render-layer).**

---

## Request 3 — show WHO changed a configmap/deployment and WHEN (human vs automation)

This is the most valuable and the most involved — but the enabling data is
**already one field away**.

### What exists today
`recent_changes()` (cluster impl) already reads each object's
`managedFields[].time` to get the **when** (last-edit time) and surfaces it as
the change's `at`. But it **discards `managedFields[].manager`** — the actor
that made the edit. Kubernetes records the manager name there, e.g.:
- `kubectl-edit` / `kubectl-client-side-apply` → a human ran kubectl
- `helm` → a Helm release
- `argocd-application-controller` → GitOps/Argo
- `<operator>-controller` → an operator/automation
That manager string is exactly the human-vs-automation signal you want.

### The fix
1. **`query_tools.py`** — new helper `_managed_fields_actor(obj)` returning
   `(time, manager, operation)` for the newest managedFields entry (not just
   the max time). Thread `manager` (and the `operation`: `Update`/`Apply`)
   into every `_change(...)` call via two new dict keys: `actor` and
   `operation`. Applies to configmap/secret/deployment/statefulset changes.
   Rollouts (new ReplicaSet) similarly: read the RS's own managedFields
   manager.
2. **Classify actor → source** (a tiny lookup): map common manager prefixes to
   a human-readable `source` label + an `is_automation` boolean:
   - `kubectl*`, `oc` → "human (kubectl/oc)", automation=false
   - `helm*` → "Helm", automation=true
   - `argocd*`, `flux*` → "GitOps", automation=true
   - `*-controller`, `*-operator`, `kube-controller-manager` → "controller/operator",
     automation=true
   - anything else → shown verbatim, automation=unknown.
   This is best-effort labeling; the raw manager string is always shown too so
   nothing is hidden behind the classification.
3. **Carry it through the reasoning → report**: `reasoning/steps.py`
   `change_correlation` already turns each change into an `Evidence` with a
   `Citation(kind="change", ...)`. Extend the evidence `summary` and the
   citation `detail` to include `by <actor> (<source>) at <time>`, e.g.
   `Recent configmap_update on upf-config by kubectl-edit (human) at
   2026-10-28T08:58:12Z`. No schema change needed — `Citation` already has
   `source`, `detail`, `timestamp` fields; we just populate them richer.
   (If we want it as first-class structured data rather than in the detail
   string, add optional `actor`/`source` fields to `Citation` — a clean,
   backward-compatible addition. Recommend doing this so the UI can render it
   as its own column rather than parsing a string.)
4. **UI — Incident detail** (`_incident_detail.html`): in the evidence chain /
   citations for a change, render a dedicated line:
   `👤 kubectl-edit (human) · 🕒 2026-10-28 08:58:12` or
   `🤖 argocd-application-controller (GitOps) · 🕒 …`. The 🕒 timestamp is the
   precise `managedFields[].time`, already captured.

### Honest limitation to call out
`managedFields.manager` tells you the **tool/controller** that made the edit
(kubectl, helm, an operator) and the **time** — reliably, with no extra
permissions (it's in the object we already read). It does **not** give the
**username** of the human behind a `kubectl` edit. The real username lives in
the **Kubernetes audit log**, which:
  - requires cluster audit logging to be enabled (often off), and
  - requires access to the API server audit backend / a log store — not
    something the read-only `get/list/watch` ServiceAccount can reach.
So: we can reliably answer **"human kubectl vs Helm vs Argo vs operator, and
exactly when"** from data we already have. We can *not* answer "which named
person" without the audit log. The plan delivers the former now and documents
the latter as a follow-up requiring audit-log access (a separate, larger
integration). This distinction is important so the feature isn't oversold.

### Why valuable
This directly serves your stated goal — "determine whether the change was
human error or an automation script" — which the manager field answers
directly in the common case (kubectl/oc = human; helm/argo/operator =
automation).

**Effort: ~2–3 h (helper + classification + plumb through reasoning + UI +
tests). Risk: low-medium — the managedFields shape varies, so defensive
parsing + a unit test over sample objects is needed. Stub `recent_changes`
also updated so tests/demo show the new fields.**

---

## Suggested sequencing

1. **Req 1 (breakdown)** — quickest, immediately clarifies the headline number.
2. **Req 2 (legend + distinct icons)** — self-contained render change.
3. **Req 3 (change attribution)** — most valuable; do last as it spans
   query_tools → reasoning → models → UI, with tests at each layer.

All three are additive and read-only; none touches the cluster-write boundary.
I'll version-bump to 0.6.0, run the 98-test suite + ruff, rebuild/re-measure
the image (expected to stay ~89 MB — no new heavy deps), and re-package for
Cobra, per the usual flow.

## Open choice for you (won't block me — I'll pick the default if silent)
For Req 3, structured `Citation.actor`/`source` fields (UI renders a clean
column) **[default]** vs. just enriching the existing `detail` string (zero
schema change, slightly messier UI). I recommend the structured fields.
