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
  phase + statuses.
- 🟡 **`calls` edges (0.3.5)** — real NF-to-NF topology from a maintained
  static service map or OTel tracing is still 🔲 (no authoritative source
  exists for a static map — fabricating one would violate "everything is
  cited"; OTel is new infra not to be stood up on someone else's cluster
  unasked). What 0.3.5 *does* build: `_add_call_edges` in `graph/builder.py`
  scans each pod's literal env var values and the ConfigMap data it mounts
  or reads via `envFrom`/`configMapKeyRef`, for a DNS-boundary-safe match
  against another Service's name already in the graph (e.g.
  `VAULT_ADDR=https://eric-cloud-native-backupless-key-management:8200`
  → a cited `calls` edge to that Service). Services also now get a real
  health rollup (`roll_up_service_health`, from the pods they `select`) —
  without it a `calls` edge to a service would be meaningless, since the
  service node would always read as "healthy" by default. `graph_walk`
  (`reasoning/steps.py`) cites the exact env var/ConfigMap key on the
  resulting evidence. **This never invents a dependency** — a pod with no
  such literal reference gets no edge, same evidence-only discipline as the
  rest of the project. Covered by `tests/test_cluster_graph.py` (9 new
  tests: edge creation, DNS-boundary safety, `configMapKeyRef` resolution,
  mounted-ConfigMap-data scanning, self-reference exclusion, service health
  rollup) and `tests/test_pipeline_cluster.py` (one end-to-end: an upstream
  Service hypothesis with a cited env-var evidence, not a generic guess).
  **Found and fixed along the way**: `DependencyGraph.upsert_node`'s
  "node already exists" path never backfilled `kind` on a node that had
  been implicitly auto-created by `add_edge` before anything explicitly
  upserted it — a real latent bug the calls-edge work's build order exposed
  (service nodes silently lost their `kind`, so the health-rollup loop
  skipped them). Fixed with a `setdefault`.
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
  **Validated on the real Cobra cluster, 2026-10-27**: all 12 `eric-pc-sm-*`
  incidents came back with `related_count: 11`, `related_incidents` listing
  the other 11 ids, and a correlation note naming all 11 sibling pods by
  name — with each hypothesis's confidence left untouched at 0.50.
  **Further progress in 0.3.5**: the "real fix" above — naming *which*
  dependency is shared — now exists as a mechanism (`calls` edges from env
  var / ConfigMap references, see Phase 1). Whether it actually fires on
  THIS specific outage depends on whether the real `eric-pc-sm-*` pods
  reference their shared dependency by name in an env var or ConfigMap —
  unverified as of this writing (see "Testing 0.3.5" steps below). If they
  do, the next time this fires, instead of (or alongside) the correlation
  note, the top hypothesis should gain an `upstream:service/<name>` entry
  citing the exact env var. If they don't (e.g. the dependency is reached
  via a Secret-only reference, a hardcoded address, or service discovery
  that never appears as literal text), correlation remains the only signal
  — which is the honest, non-fabricated outcome, not a bug.
  **First real-cluster data point, 2026-10-27**: for
  `eric-pc-sm-sgw-session-7d89f7cd6b-25r4z`, no `service/*` hypothesis
  appeared — still just the generic "failing health probe" one plus the
  0.3.4 correlation note.
  **Resolved, 2026-10-27**: checked `/graph/view/<pod>?radius=2` directly.
  `sgw-session`/`smf-pgw-session`/`diameter` DO reference real dependencies
  literally — `ERIC_PC_SM_DB_SERVICE_NAME=eric-pc-kvdb-rd-server`,
  `ERIC_PC_SM_TARGET_DB_MASTER_SERVICE_NAME=eric-pc-sm-target-database-master-rd`,
  `..._REPLICA_SERVICE_NAME=eric-pc-sm-target-database-replica-rd`,
  `ERIC_PC_VGF_SERVICE_NAME=eric-pc-vpn-gateway-forwarder...` (referenced by
  ALL THREE, including `diameter`, which has no DB reference) — and 0.3.5's
  `calls` edges DID get built for all of these. But all four resolve to
  **healthy** services (`eric-pc-kvdb-rd-server` 6/6, both target-database
  services 1/1, `eric-pc-vpn-gateway-forwarder` 2/2) — so `unhealthy_upstream`
  correctly finds nothing to report. **Even with the mechanism working and
  real references found, this specific outage genuinely isn't a
  "referenced dependency is down" cascade** — reinforces the earlier manual
  conclusion (cm-mediator healthy, its cert valid for another ~100 years)
  that the cause is internal to the 6 affected components, not an external
  dependency.
  **A real bug found in the same test, fixed in 0.3.6→0.3.7**: the dump also
  showed calls edges from nearly every pod (including `diameter`, which has
  no such literal env values) to `eric-cm-mediator`/`eric-sec-sip-tls`/
  `eric-pm-server`/`eric-cm-yang-provider` — all false positives. Cause: the
  boundary regex used `\b`, and a hyphen counts as a word boundary, so
  `\beric-cm-mediator\b` also matched inside `eric-cm-mediator-tls-client-
  ca-secret` — a DIFFERENT, longer secret name that merely starts with the
  same prefix. Since this stack names nearly every secret/configmap
  `<component>-<descriptor>-secret`, this fired constantly, polluting the
  graph with calls edges across nearly the whole namespace. Fixed by
  requiring the character immediately before/after the match to be neither
  alphanumeric nor a hyphen (`_boundary_re` in `graph/builder.py`), so a
  service name can only match as a COMPLETE hyphen-delimited token, never a
  prefix/suffix of a longer one. New regression test:
  `test_calls_edge_not_created_when_service_name_is_a_prefix_of_a_longer_hyphenated_name`.
  **Validated on the real Cobra cluster, 2026-10-27**: after deploying 0.3.7,
  `diameter`'s `calls` edges dropped from 6 to the 2 genuine ones
  (`service/eric-pc-vpn-gateway-forwarder`, `service/eric-log-transformer`)
  — all 4 false positives (`eric-cm-mediator`/`eric-sec-sip-tls`/
  `eric-pm-server`/`eric-cm-yang-provider`) gone, exactly as predicted. This
  closes out the `eric-pc-sm-*` investigation: the mechanism is correct, the
  genuine dependencies it found are all healthy, and the outage's true
  cause remains internal to the 6 affected components — not discoverable
  from cluster state alone with the tools this agent has today.
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
- ✅ **Fixed (0.3.3, regressed once, fixed properly in 0.3.6) — non-ASCII
  characters in `suggested_next_steps`.** The "no runbook source configured"
  note used an em dash (`—`), which showed up as mojibake
  (`\udce2\udc80\udc94`) when piped through `python3 -m json.tool` on the
  Cobra jumpserver's RHEL 8.8 shell (non-UTF-8 locale mis-decoding the UTF-8
  bytes). Fixed in 0.3.3 by using a plain ASCII `-`. **Then the exact same
  bug reappeared independently in 0.3.4**: the new "Correlated: ..." note
  (`detection/event_watcher.py::_apply_correlation_note`) used its own em
  dash, written in the same session that fixed the first one, and wasn't
  caught until the next real-cluster test. Patching one string at a time
  doesn't work. Fixed in 0.3.6 by (a) a repo-wide grep for `—` outside
  comments/docstrings to confirm no other live instance exists (the HTML
  page title and `/graph/view` dropdown text also use em dashes but are
  browser-rendered, not JSON — left as-is), and (b) a real regression test,
  `tests/test_ascii_safety.py`, that recursively scans an actual serialized
  `IncidentReport` (including the exact correlation-note code path) for any
  character with `ord(c) > 127`. This is the systemic fix — it catches a
  *third* non-ASCII character introduced anywhere in future reasoning or
  detection output, not just these two specific strings.
- 🔲 **Open — `oc get events` column-position scripting is fragile.** While
  testing the watcher's conservative filter, a one-liner using
  `awk '{print $2}'` against `oc get events` table output accidentally
  printed the TYPE column (always "Warning" once filtered) instead of REASON
  ($3), because the "LAST SEEN" header splits into two words but the data
  value doesn't. Not a code bug — a reminder for any future runbook/tooling
  text in this repo: prefer `-o jsonpath='{.items[*].reason}'` over
  column-counting against `oc`/`kubectl` table output.

---

## Testing 0.3.5 on the real Cobra cluster

The automated suite (`tests/test_cluster_graph.py`, `tests/test_pipeline_cluster.py`)
proves the mechanism works against a fake client. These are the steps to
confirm it says something real against the actual `eric-pc-sm-*` outage —
run from the jumpserver (or via an SSH tunnel), after deploying 0.3.5.

1. **Deploy** (same pattern as every prior version):
   ```bash
   scp dist/cobra-package-0.3.5/{rca-agent-0.3.5.tar.gz,rca-agent-0.3.5.tar.gz.sha256,deploy-cobra.sh} \
       eagamil@10.242.70.7:~/
   ssh eagamil@10.242.70.7
   oc login https://api.cobra-2a-openshift.bete.ericy.com:6443 -u eagamil -p <password> --insecure-skip-tls-verify
   chmod +x deploy-cobra.sh && ./deploy-cobra.sh
   ```

2. **Confirm `calls` edges actually got built.** This is the step that
   answers the open question above — whether the real pods reference their
   dependencies by name in env vars/ConfigMaps at all:
   ```bash
   curl -s http://10.242.70.7:8004/graph/view/eric-pc-sm-diameter-7bdcb67999-7tcd2?radius=2
   ```
   Open in a browser; look for any edge labeled `calls` leaving that pod. If
   none exist, `0 calls edges built` is the honest (if less exciting)
   outcome for this specific pod — check a few other `eric-pc-sm-*` pods too
   (`ip-allocator`, `sgw-session`, `udp-forwarder`) since different
   components may be configured differently.

3. **Check the incident report for a NAMED upstream cause**, not just the
   correlation note from 0.3.4:
   ```bash
   curl -s http://10.242.70.7:8004/incidents | python3 -c "
   import json, sys
   d = json.load(sys.stdin)
   print([i['incident_id'] for i in d['incidents']][0:3])
   "
   # then, for one of those ids:
   curl -s http://10.242.70.7:8004/incidents/<incident_id> | python3 -m json.tool
   ```
   Look specifically for a hypothesis whose `cause` starts with
   `service/<something>` (not just `<pod> failing health probe`) — that's
   the calls-edge feature naming an actual upstream dependency. Check its
   `evidence_chain`/`supporting_evidence` for an `env:<VAR>` or
   `configmap:<name>.<key>` citation.

4. **If no `service/*` hypothesis appears anywhere**, that's useful
   information, not a failure: it means the shared `eric-pc-sm-*` dependency
   isn't referenced by name in any pod's env vars or ConfigMap data (common
   if it's reached via a Secret, a hardcoded address, or app-level service
   discovery). Confirm by hand what IS shared:
   ```bash
   oc get pod eric-pc-sm-diameter-7bdcb67999-7tcd2 \
     -n plantx2avzwcspgc-y-oc-consp-301 -o jsonpath='{.spec.containers[0].env}' \
     | python3 -m json.tool
   ```
   If the real dependency only shows up in a Secret, that's a deliberate
   scope boundary of this feature (see Phase 1 above), not a bug — the next
   step would be a conscious decision to also scan Secret values, trading
   some of the "never touch anything sensitive" caution for more coverage.

5. **Regression-check the rest of 0.3.4's behavior still holds** (the
   correlation note should still appear alongside any new calls-edge
   hypothesis, not replaced by it):
   ```bash
   curl -s http://10.242.70.7:8004/incidents/<incident_id> | python3 -c "
   import json, sys
   r = json.load(sys.stdin)
   print('related_count via related_incidents:', len(r['related_incidents']))
   print([s for s in r['suggested_next_steps'] if s.startswith('Correlated:')])
   "
   ```

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
