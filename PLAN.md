# POC Roadmap — 4 Weekly Phases

Goal: ranked root causes **without an LLM by week 2**; **baseline comparison in
week 4**. Each phase ends with something demoable.

Legend: ✅ scaffolded in this repo · 🔲 to build.

---

## Phase 1 — Cluster + detection + live graph (Week 1)

Stand up the environment and turn real cluster state into a graph.

- 🔲 **Cluster**: `kind`/`k3d` with Open5GS (Online Boutique as lighter fallback).
- 🔲 **Observability**: `kube-prometheus-stack`, Loki, OpenTelemetry/Jaeger.
- ✅ **Webhook**: FastAPI `/webhook/alertmanager` + `/healthz` `/readyz`.
- 🔲 **Alertmanager rules**: error rate, latency, restarts, pod-not-ready → webhook.
- ✅ **Event watcher** (0.3.3, `detection/event_watcher.py`): background poll
  (`RCA_EVENT_WATCH_INTERVAL_SECONDS`, default 15s) of K8s Warning events in
  the monitored namespace for the named fault reasons (CrashLoopBackOff,
  OOMKilled, ImagePullBackOff, FailedScheduling, Unhealthy, FailedMount,
  NodeNotReady, Evicted — deliberately NOT "any Warning event", to avoid
  flooding on transient cluster noise) → feeds the SAME `ReasoningFlow` the
  webhook uses, no hand-crafted alert payload needed. Scoped automatically to
  whatever the graph already monitors (only acts on events naming a node that
  exists in the current graph); deduped by event UID so a long-lived
  CrashLoopBackOff isn't re-diagnosed every poll. Results land in the new
  `GET /incidents` (summary list) and `GET /incidents/{id}` (full report)
  endpoints — in-memory only, bounded to the last 200 (Postgres persistence is
  still Phase 3). Node-pressure events and Alertmanager-rule-based detection
  (needs an observability stack — still 🔲) are not covered by this watcher.
  **Validated on the real Cobra cluster, 2026-10-27**: auto-detected 12/12
  `Unhealthy` events with zero manual webhook POSTs (exact match against
  `oc get events`); dedup held at 12 across multiple poll cycles with the
  same pods still unhealthy; the one non-fault Warning event in the namespace
  (`ConfigDuplicateKey`) was correctly left out of `/incidents`.
- ✅ **Graph build from cluster** (`graph/builder.py::_rebuild_from_cluster`):
  list pods/nodes/deployments/configmaps via the read-only client; build
  `runs_on`/`mounts`/`managed_by` from owner refs & volumes. Health from pod
  phase + statuses. **Still missing: `calls` edges** (static service map or
  OTel traces) — no NF-to-NF topology exists yet, so `graph_walk` can't find
  upstream causes or blast radius for a dependency failure (see Known Issues).
- ✅ **Read-only RBAC** Helm chart (get/list/watch only).

**Exit**: an alert hits the webhook and the agent returns an evidence table +
candidate causes from real cluster state.

---

## Phase 2 — Reasoning quality + runbook RAG + UI (Week 2)

Make the ranked output good, and wire the LLM as a re-ranker only.

- ✅ **Extractive pipeline** (triage → gather → graph walk → change correlation
  → hypothesize/rank → report), fully deterministic and reproducible.
- ✅ **KubeQueryTools**: implemented in `tools/query_tools.py` against the
  read-only client (pod status, events, logs — prefers `previous` for crashed
  containers —, optional PromQL, recent changes).
- ✅ **Change correlation from real sources**: ConfigMap/Secret updates (via
  real `managedFields[].time`, HA-bookkeeping objects excluded), new
  ReplicaSet revisions (rollouts/image changes), Deployment spec updates.
  As of 0.3.2, correlation is also *scoped*: a config/secret edit only counts
  as a candidate cause when the affected pod's graph `mounts` edges show it
  actually consumes that object (uncorrelated edits are kept as evidence but
  weighted far lower so they can't outrank the real fault). Node events /
  scaling / audit-log changes still 🔲.
- 🔲 **LangGraph flow** (`reasoning/flow.py`): StateGraph of the same steps +
  a final LLM node that only *re-ranks & explains* existing hypotheses.
  Reject any cause not already evidence-backed. Untrusted text stays fenced.
- 🔲 **Runbook RAG**: `HttpRunbookRetriever` against the existing
  doc-intelligence service; populate suggested next steps + citations.
- 🔲 **UI**: Streamlit incident list + report view; reuse the GraphRAG **Impact
  Explorer** (`/graph/neighborhood/{node}`) to show the failing pod's
  neighborhood with unhealthy nodes highlighted.

**Exit**: ranked root causes with evidence chains and runbook next-steps, in
both extractive and LLM modes, viewable in the UI.

### Reasoning-quality fixes shipped ahead of schedule (0.3.2, 2026-10-27)

Found by hand-testing real pods on the Cobra cluster (manually crafting an
Alertmanager webhook POST per red pod — see Known Issues below for why this
should become automatic):

- ✅ **Probe-failure hypotheses** — a pod that is `Running` but failing its
  readiness/liveness probe (no OOMKilled/CrashLoopBackOff) now scores as a
  standalone fault (`_detect_probe_failure` in `reasoning/steps.py`) instead of
  producing no hypothesis at all.
- ✅ **Honest runbook fallback** — with no `runbook_rag_url` configured,
  `suggested_next_steps` now says so explicitly (`NullRunbookRetriever` +
  neutral note) instead of emitting `StubRunbookRetriever`'s canned UPF/SMF
  text against an unrelated real pod.

---

## Known Issues (found via live-cluster testing, not caught by pytest)

- 🟡 **Partially fixed (0.3.4) — no root-cause unification across
  simultaneous related failures.** Found 2026-10-27, via the 0.3.3 event
  watcher on the real Cobra cluster: 12 pods across 6 `eric-pc-sm-*`
  components (`diameter`, `geo-red-forwarder`, `ip-allocator`, `sgw-session`,
  `smf-pgw-session`, `udp-forwarder` — both replicas of each) were all
  `1/2 Running`, all failing the *identical* `GET /ready` → `HTTP 500` probe,
  for 3-6 days with zero restarts. `controller`/`br-agent` (unaffected) and
  the shared `target-database-master-rd`/`replica-rd` pods (`2/2 Running` at
  the pod level) point at one shared dependency — but the agent reported
  **12 separate incidents**, each a low-confidence (0.50) "pod X failing
  health probe" with no shared cause named and an empty `blast_radius`.
  Direct consequence of the missing `calls`/topology edges (Phase 1).
  **What 0.3.4 does, and deliberately does NOT do**: real `calls` edges need
  either a maintained static service map (no authoritative source exists —
  guessing one would fabricate exactly the kind of unsupported claim this
  project exists to avoid) or OTel tracing (new infra, not something to
  stand up on someone else's cluster unasked). So instead,
  `detection/event_watcher.py::_correlate` deterministically **links**
  incidents that share an identical failure *signature* (hypothesis text
  with the resource name blanked out) on a different resource within
  `incident_correlation_window_minutes` (default 10) — new
  `related_incidents` field on `IncidentReport`, surfaced as `related_count`
  in `GET /incidents` and a `"Correlated: N other resource(s) failed
  identically..."` note in `suggested_next_steps`. It links; it never claims
  or ranks a specific shared cause. The real fix — naming *which* dependency
  is shared — is still 🔲 and still needs real topology data. Manually-posted
  webhook incidents now share the same pool/timeline as auto-detected ones
  (`EventWatcher.record_external_incident`), so correlation works across
  both. Compounds with the item below: there were no logs to extract a
  shared hostname from anyway, so this was the only grounded fix available.
- 🔲 **Open — log-content root-cause extraction.** The reasoning pipeline
  fences and lists raw log lines as evidence but never parses them for a
  structural failure signal. Found 2026-10-27 testing the real
  `eric-cloud-native-backupless-key-management-configurer-*` pod on Cobra: its
  logs clearly showed `Connection refused` trying to reach
  `eric-cloud-native-backupless-key-management:8200` (Vault), but the top
  hypothesis stayed at the generic "readiness probe failing" — the actual
  upstream dependency was never named. Two compounding causes: (a) no
  log-pattern step exists to turn a `host:port` connection-refused/timeout
  line into its own hypothesis, and (b) the real-cluster graph still has no
  `calls` edges (see Phase 1), so even if the host were extracted,
  `graph_walk` has no NF-to-NF edge to confirm it against or compute blast
  radius from. Candidate fix: a log-pattern step that extracts `host:port`
  from connection-refused/DNS/TLS-handshake lines, matches it against known
  service/pod names in the graph, and — if matched — promotes it to its own
  "unhealthy upstream dependency" hypothesis with its own evidence chain.
  **Caveat found 2026-10-27 on the `eric-pc-sm-*` outage above**: this fix
  won't always have something to parse — those 12 pods' app containers log
  nothing to stdout at all (this platform ships logs via an ADP `logshipper`
  sidecar instead), so `oc logs`/our `tools.logs()` are both blind on them.
  Any log-pattern step is necessarily a partial fix, not a substitute for
  real `calls` edges.
- ✅ **Fixed — mis-rendered non-ASCII character in `suggested_next_steps`.**
  The new "no runbook source configured" note (added for the fix above) used
  an em dash (`—`), which showed up as mojibake (`\udce2\udc80\udc94`) when
  piped through `python3 -m json.tool` on the Cobra jumpserver's RHEL 8.8
  shell (non-UTF-8 locale mis-decoding the UTF-8 bytes). Fixed by using a
  plain ASCII `-` in that string (shipped in 0.3.3). A reminder that any
  user-facing string returned over the webhook API should stay ASCII-only
  until verified safe across target environments — not just the dev
  machine's locale.
- 🔲 **Open — `oc get events` column-position scripting is fragile.** While
  testing the watcher's conservative filter, a one-liner using
  `awk '{print $2}'` against `oc get events` table output accidentally
  printed the TYPE column (always "Warning" once filtered) instead of REASON
  ($3), because the "LAST SEEN" header splits into two words but the data
  value doesn't. Not a code bug — a reminder for any future runbook/tooling
  text in this repo: prefer `-o jsonpath='{.items[*].reason}'` over
  column-counting against `oc`/`kubectl` table output.

---

## Phase 3 — Persistence + chaos harness (Week 3)

Make incidents durable and build the evaluation rig.

- 🔲 **Postgres**: persist incidents & reports; incident list reads from it.
- 🔲 **Chaos Mesh**: install and template the fault set.
- 🔲 **Fault library** (labeled test cases — true cause is known):
  1. Kill the UPF pod → SMF errors downstream.
  2. Lower a memory limit → pod OOMKilled.
  3. Bad ConfigMap value (wrong service address).
  4. Network latency / packet loss between two NFs.
  5. Bad image tag → ImagePullBackOff.
  6. Drain/taint a node → unschedulable pods.
  7. CPU exhaustion on one service.
  8. Two simultaneous faults (does the agent separate them?).
- 🔲 **Runner script**: inject → wait → collect report → score → clean up.

**Exit**: one command injects a fault and produces a scored incident report.

---

## Phase 4 — Evaluation + baselines + write-up (Week 4)

Prove the graph matters.

- 🔲 **Metrics**: detection time, top-1 / top-3 accuracy, time to diagnosis,
  evidence quality (do citations support the claims?).
- 🔲 **Baselines**: (a) alert alone; (b) plain LLM given logs but no graph.
- 🔲 **Results table** across the fault library, auto-generated by the runner.
- 🔲 **Headline**: graph version vs. no-graph version.
- 🔲 **Honest limitations**: rule-based detection, single cluster, synthetic
  faults, diagnosis-only. Remediation is the clean next phase (the read-only
  design makes it an additive extension, not a rewrite).

**Exit**: a results table + narrative suitable for the article.

---

## Design invariants (hold across all phases)

- **Read-only by construction** — RBAC `get/list/watch` only; no write tool exists.
- **Rules first, LLM second** — deterministic evidence & candidates; the LLM only
  ranks/explains and cannot invent unsupported causes.
- **Everything is cited** — each claim links to a log line, metric, event,
  change, graph edge, or runbook page.
- **Untrusted input is fenced** — logs/alert text wrapped as data
  (prompt-injection defense).
- **Timestamped graph** — reconstruct the graph as it was when the fault started.
