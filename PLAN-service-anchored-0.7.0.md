# Plan: service-anchored incident model (0.7.0)

Shift the unit of analysis from **pod** to **workload/service anchor, with pods
as the evidence layer** — keeping pod-level fault detail while fixing the
blast-radius asymmetry, replica-noise, and stale-pod-name problems. Not a flip
to "service only"; a hybrid anchored on the service/workload with a pod
fallback.

## Why (recap, grounded in the code)
- `calls` edges always end at `service/` nodes (`builder.py:516`), but incidents
  are anchored on the **pod** (`affected_resource = alert.target`), so
  `downstream(pod)` is structurally almost always empty → the "downstream
  confusion" you observed.
- 12 identical `eric-pc-sm-*` pod failures became 12 incidents needing the
  correlation feature to re-link; a service anchor aggregates replicas natively.
- Pod names churn (hashes change each rollout); a service/workload anchor is
  stable over the incident's life.
- `roll_up_service_health` / `roll_up_health` already compute service & workload
  health from pods — the anchor's headline signal already exists.

## Design: the "anchor"
For any fault signal on a pod, resolve a single **anchor**:
1. the **Service** that `selects` the pod (preferred), else
2. the owning **workload** (Deployment/StatefulSet/DaemonSet via `managed_by`),
   else
3. the **pod itself** (bare Job/standalone pod — the fallback, so Jobs and
   DaemonSet members without a Service still get an incident).

The incident is anchored there; the triggering pod(s) become evidence.

---

## Phase 1 — resolve-to-anchor at detection + model fields (low risk)
Keep the UI and reasoning mostly intact; just add the anchor concept.

1. **`dependency_graph.py`**: add `anchor_of(pod_id) -> {kind, id, display}` using
   existing `selects` (service) and `managed_by` (workload) edges, with the pod
   as fallback. Add `pods_of_anchor(anchor_id) -> [pod_ids]` (reverse: a
   service's selected pods / a workload's managed pods).
2. **`models/incident.py`**: add
   - `affected_anchor: str | None` (service/workload id),
   - `anchor_kind: str | None` ("service"/"deployment"/"pod"),
   - `affected_pods: list[str]` (the pod evidence behind the anchor).
   All optional/back-compatible; `affected_resource` stays (= the anchor's
   display or the pod when pod-anchored) so nothing breaks.
3. **`event_watcher.py`**: on a pod fault event / persistent-unhealthy pod,
   resolve the anchor; **dedup incidents by anchor** within the poll window, so
   12 sibling pods failing the same way produce **one** anchor incident with 12
   pods in `affected_pods` instead of 12 incidents. (This is where replica
   aggregation happens natively.)
4. Tests: anchor resolution (service / workload / bare-pod fallback); 12 sibling
   pods → 1 anchor incident.

**Outcome after P1:** incidents already aggregate by service; the model carries
the anchor + pod evidence. UI unchanged (still shows `affected_resource`).

---

## Phase 2 — service-centric incident detail + symmetric blast radius
Make the reasoning + UI use the anchor as the headline.

5. **`reasoning/steps.py` `graph_walk`**: compute upstream/downstream from the
   **anchor** (the service node), not the pod. This makes
   - upstream = services the anchor depends on (unhealthy ⇒ candidate cause),
   - downstream = services that `calls` the anchor (**the real blast radius**),
   symmetric — fixing the always-empty-downstream bug for free (no pod↔service
   bridging hack needed; the anchor *is* the service).
6. **`graph.py` owners/health**: headline = service/workload health rollup
   ("yang-provider: degraded, 2/3 pods ready"), already computed.
7. **UI `_incident_detail.html`**:
   - **Header** = anchor: `service eric-cm-yang-provider — degraded (2/3 ready)`.
   - **Affected pods** block = the `affected_pods` with each one's fault reason
     (OOMKilled / probe-500 / CrashLoop) — the pod-level *why*, preserved as
     evidence under the service headline.
   - **Impact & dependencies** = upstream/downstream from the anchor
     (now both populate), still two separate blocks.
8. **PPTX** (`pptx_report.py`): "Where" = the service/workload; the
   sequence-of-events swimlanes already group by actor; add the affected-pods
   list to slide 1.
9. Tests: anchor-based upstream/downstream populate symmetrically on a graph
   with real `calls` edges; UI detail renders the affected-pods block.

**Outcome after P2:** the dashboard is service-centric (service headline, pod
drill-down), blast radius works both directions.

---

## Phase 3 — retire / repurpose correlation
10. With anchor-dedup in P1, the 0.3.4 correlation feature (link N identical
    pod incidents) is largely **subsumed** — the anchor already groups siblings.
    Repurpose it to link incidents across **different anchors** that share a
    failure signature (e.g. 5 different services all failing probes at once →
    still a useful cross-service pattern), or retire it if that adds noise.
    Decide with real-cluster data, not speculatively.

---

## What we deliberately keep (so nothing regresses)
- **Pod-level fault detail** — the *reason* (OOMKilled/probe-500/CrashLoop) lives
  on pods and is kept as evidence; the anchor is the headline, not a replacement.
- **Bare-pod fallback** — Jobs/standalone pods with no Service/workload stay
  pod-anchored, so nothing goes undetected.
- **Read-only, single process, ~104 MB image** — no new deps, no architecture
  change beyond the reasoning entry point.

## Honest caveats
- Blast radius is still only as complete as the `calls` edges (env-var/ConfigMap
  heuristic — no traces/mesh). P2 makes it *symmetric and non-empty*, not
  *exhaustive*. Documented as such.
- Some genuinely pod-specific faults (one bad replica on one node) are better
  seen per-pod; the affected-pods block preserves that detail so it isn't lost
  to aggregation.
- Phase 1 is safe and high-value on its own (replica aggregation + model). Phase
  2 is the visible service-centric shift. Ship P1 first, validate on Cobra,
  then P2.

## Sequencing & versions
- **0.7.0-rc1 = Phase 1** (anchor model + dedup; UI unchanged) — shippable,
  immediately kills the 12-incidents-per-outage noise.
- **0.7.0 = Phase 2** (service-centric detail + symmetric blast radius).
- **0.7.1 = Phase 3** (correlation decision), data-driven after P2 runs on Cobra.

All phases: tests + ruff + build + package per the usual flow; verify on Cobra
between P1 and P2.
