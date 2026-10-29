# Plan: blast radius in incident detail + multi-namespace support

## Request 3 (answered first — it drives #2)

**Can the system build & store a separate graph per namespace without
overwriting? YES — cleanly.** Today there's a single `GraphBuilder` holding one
`DependencyGraph` (`self._graph`), rebuilt for `settings.namespace`; each
`rebuild()` replaces it, so it's single-namespace by construction. But a
`DependencyGraph` is a self-contained object with no global state, and node IDs
are per-object names — so the right design is a **registry keyed by namespace**:
`{namespace -> (GraphBuilder, DependencyGraph, EventWatcher)}`. Each namespace's
graph is built, refreshed, and queried independently; nothing overwrites
anything. This is a contained addition, not a rewrite.

---

## Request 1 — show blast radius (upstream + downstream) in the Incident detail

### Current state (verified)
The reasoning already computes both directions in `graph_walk`:
- `state.unhealthy_upstream = graph.unhealthy_upstream(res)` → candidate causes
- `state.blast_radius = graph.downstream(res)` → impacted dependents

`IncidentReport` already has a `blast_radius: list[str]` field, and it's
populated. **It's just not rendered in the UI detail panel.** Upstream is
currently only visible indirectly (as cascade hypotheses), not as an explicit
"caused-by chain" block.

### The fix (small, mostly UI)
1. **`reasoning/steps.py`** — also surface the *upstream* set on the report so
   the UI can show both directions explicitly. `blast_radius` (downstream) is
   already there; add the upstream dependency list to the report too (either a
   new `IncidentReport.upstream_unhealthy: list[str]` field — clean — or reuse
   the existing evidence). Recommend the explicit field: one-line model add,
   populated in `graph_walk`.
2. **`webhook/ui.py` detail route** — already passes the full report dict; no
   change needed beyond the template.
3. **`_incident_detail.html`** — add a **"Impact & dependencies"** section:
   - **Upstream (possible causes):** the unhealthy upstream deps, each as
     `affected-pod ⬅ upstream-service (unhealthy)`, with the `calls`-edge
     evidence (which env var / ConfigMap key created the dependency) when
     present.
   - **Downstream (blast radius):** `affected-pod ➡ dependent-A, dependent-B …`
     — i.e. "these services/jobs are impacted because this is down."
   - Render as a compact two-column block or two labeled lists. If both are
     empty (common today, since the single-app graph has few `calls` edges),
     show a muted "no cross-service dependencies in the current graph" note so
     it's honest rather than blank.
4. **Make resource identity explicit.** You noted the detail "talks about the
   incident but doesn't say which pod → which job/service is down." Fix: the
   detail header already has `affected_resource`; extend it to also show the
   **owning workload/service** by walking the graph (`managed_by` up to the
   Deployment/StatefulSet, and any Service that `selects` the pod). So the
   header reads e.g.
   `pod upf-1  ·  workload: upf (Deployment)  ·  service: upf  ·  🔴 critical`.
   This needs a tiny graph lookup exposed to the UI (e.g.
   `graph.owners(pod)` returning `{workload, service}`), then rendered.

**Effort: ~1.5 h (one model field + 2 small graph helpers + template block).
Risk: low. No cluster-write surface touched.**

---

## Requests 2 & 3 together — multi-namespace: pick a namespace in the UI,
## build/store its graph separately, scope all tabs to it

### Design: a namespace registry + lazy, on-select building

**Default-eager, rest-lazy** (exactly your ask): the namespace given in the
`docker run` (`RCA_NAMESPACE`) is built at startup as today. Other namespaces
are built **only when the user selects them** — nothing is gathered upfront for
them.

1. **`GraphRegistry` (new, `graph/registry.py`)** — holds
   `{namespace -> NamespaceContext}` where `NamespaceContext` bundles that
   namespace's own `GraphBuilder`, its `DependencyGraph`, and its
   `EventWatcher` (so incidents are per-namespace too). Methods:
   - `default_namespace` — the `RCA_NAMESPACE` one, built eagerly.
   - `ensure(ns)` — build-on-first-use: creates + rebuilds that namespace's
     context in a background thread, returns immediately with a "building…"
     status so the UI isn't blocked. Subsequent calls return the cached one.
   - `get(ns)` / `active` — the currently-selected namespace for the UI.
   - never overwrites: each namespace keeps its own graph + incident list.
2. **List accessible namespaces** — a read-only `list_namespaces()` on the kube
   client (`kubectl get namespaces` / OCP `projects`). RBAC-safe: if the
   ServiceAccount can't list cluster namespaces, fall back to "only the
   configured one" and show that. (Many OCP users can only see projects they're
   granted — we show exactly what `list` returns, no more.)
3. **App wiring (`app.py`)** — replace the single `_graph_builder`/
   `_event_watcher`/`_flow` module globals with a single `_registry`. The
   existing endpoints (`/graph/*`, `/incidents*`, `/ui/*`) gain an optional
   `?ns=<namespace>` (default = the registry's active/selected namespace).
   The background refresh + event-watch loops iterate over **built** namespaces
   only.
4. **UI**
   - A **namespace picker** in the top bar (your "link → dropdown"): lists
     accessible namespaces, marks the default, shows a dot for
     already-built vs not-yet-built. Selecting one calls
     `POST /ui/namespace {ns}` → `registry.ensure(ns)` + sets it active →
     HTMX refreshes the metrics + current tab. While it builds, the tab shows
     a "building graph for <ns>…" spinner that polls until `readyz(ns)`.
   - Every tab fragment already re-fetches on tab-switch; they just pass the
     active `ns` through. Graph iframe becomes `/graph/view?ns=<ns>`.
     Incidents/Runbooks/QueryLog scope to that namespace's context.
     (Runbook store + query log: decide whether these are global or
     per-namespace — recommend **global** store, **per-namespace** query-log
     view, since runbooks are reusable across namespaces but "what was asked"
     is namespace-specific. Small choice, easy either way.)
5. **Resource/credentials note** — building a namespace's graph does real
   get/list calls against that namespace. Lazy-on-select means we only pay that
   cost for namespaces the user actually opens, and only with the same
   read-only token. A big namespace (the 1485-object one) already paginates +
   times out per-call, so on-select build is bounded.

### What stays unchanged (keeping this a "fix", not a rearchitecture)
- The `DependencyGraph`, reasoning pipeline, and all six steps are **untouched**
  — they already operate on "a graph"; we just hand them the selected
  namespace's graph instead of the one global one.
- Read-only RBAC, single process, single image — no change.
- Deployment still names ONE default namespace; multi-ns is an interactive
  additive capability, off until the user picks another.

### Honest caveats
- **RBAC visibility:** the namespace dropdown can only list what the token is
  allowed to `list`/see. If namespace-listing is forbidden, the UI shows just
  the configured default + a note. We never show namespaces the user can't
  access.
- **Memory:** each opened namespace keeps its graph in memory (same in-memory,
  wiped-on-restart model as today). Many large namespaces open at once = more
  memory. Mitigation (optional, later): an LRU cap on how many namespace
  contexts are retained.
- **Event watcher per namespace:** auto-detection now runs per built namespace;
  the poll loop fans out over built namespaces. Interval unchanged.

**Effort: ~1–1.5 days.**
- `GraphRegistry` + lazy build + `list_namespaces`: ~half day.
- `app.py` rewiring to registry + `?ns=` on endpoints: ~half day.
- UI namespace picker + per-tab scoping + build-progress spinner: ~half day.
**Risk: medium** — it's the one change that touches app-level wiring. Mitigated
by: the per-namespace object is just today's objects multiplied, tests per
layer, and the default-namespace path staying byte-for-byte the current
behavior when no other namespace is selected.

---

## Suggested sequencing & versioning
1. **Req 1 (blast radius + resource identity in detail)** — ship first as
   **0.5.2** (small, self-contained, immediately useful).
2. **Req 2/3 (multi-namespace registry + picker)** — larger; ship as **0.6.0**
   (it's a real capability addition, though not an architecture change — the
   reasoning core is untouched). Build the registry + lazy-build, wire the UI
   picker, verify the default-namespace path is unchanged, then re-package.

Both are additive and read-only. Image size unaffected (no new deps).
