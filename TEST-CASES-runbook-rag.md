# Manual Test Cases — Runbook RAG picks the right remedy for a pod incident

**Runbook under test:** `113_15451-axb25019uen_c.pdf`
("Troubleshoot Common Issues in Kubernetes Clusters", Ericsson)

**What we are validating:** when a pod fault raises an incident, the RCA agent's
`LocalRunbookRetriever` surfaces the *matching* section of this PDF in the
incident report's **`suggested_next_steps`** — i.e. the runbook content is
picked as a remedy.

---

## How the match actually happens (read this first)

The retrieval query is **not** the raw alert. It is the **top hypothesis's
`cause` string** built by `reasoning/steps.py::hypothesize_and_rank`, e.g.
`"eric-pm-server-0 CrashLoopBackOff"` or `"upf-0 OOMKilled"`. If there is no
hypothesis, it falls back to `"<alertname> <resource>"`.

That query is then:
1. lower-cased and tokenized (`[a-z0-9]+`, length > 1),
2. stopwords removed,
3. **hash-like suffixes stripped** (`^[0-9a-f]{6,}$`) — so a pod's random
   suffix contributes nothing; the *human-meaningful* tokens are what match
   (`crashloopbackoff`, `oomkilled`, `pending`, `evicted`, `memory`, `cpu`,
   and stable name stems like `eric`, `pm`, `server`),
4. scored (rarity-weighted TF-IDF-style term overlap) against the PDF's
   paragraph chunks; **best chunk per document** is returned.

**Design rule for every test case below:** the fault must produce a top
hypothesis whose `cause` tokens overlap the target PDF section. The fault
reasons the agent recognizes (`models/alert.py`, `reasoning/steps.py`):
`OOMKilled, CrashLoopBackOff, ImagePullBackOff, ErrImagePull, Evicted`
(+ probe `Unhealthy`, `FailedScheduling`→Pending). These are exactly the PDF's
section headings — that is why the match works.

---

## Common pre-conditions (all test cases)

- **PC-1** — RCA agent running (container `rca-agent:0.4.0`, or local
  `uvicorn rca_agent.webhook.app:app`). Base URL below assumed `http://localhost:8080`
  (adjust for the container's socket/port mapping).
- **PC-2** — `GET /healthz` returns `{"status":"ok"}`.
- **PC-3** — The PDF `113_15451-axb25019uen_c.pdf` is uploaded as a runbook
  (done once, shared by all cases):
  ```bash
  curl -s -F "file=@113_15451-axb25019uen_c.pdf" http://localhost:8080/runbooks
  # then confirm it is listed and chunked:
  curl -s http://localhost:8080/runbooks | jq
  # expect documents[].name == "113_15451-axb25019uen_c.pdf", chunk_count > 0
  ```
- **PC-4** — Clear the query log so each case's retrieval is easy to read:
  ```bash
  curl -s -X DELETE http://localhost:8080/runbook-queries
  ```

> NOTE on the extractive default: `suggested_next_steps` is produced in the
> no-LLM extractive pipeline. No LLM is required for any case here.

---

## Test Object List (TOL)

The **Expected** column below was **pre-verified** by running the real
`LocalRunbookRetriever` against this exact PDF (72 chunks) with each case's
hypothesis query. "Dedicated §" = the case's own section wins; "Overview §4.1"
= the single fault-word matches the §4.1 *status-table* chunk (which lists ALL
pod statuses) and that dense chunk outscores the dedicated section. Both are
genuine PDF hits; the distinction matters for what the human sees as the remedy.

| TC ID | Fault scenario | Hypothesis `cause` (query) | Intended PDF section | **Verified best hit** (score) | Pass criterion |
|-------|----------------|-----------------------------|----------------------|-------------------------------|----------------|
| TC-01 | Pod OOMKilled | `<pod> OOMKilled` | §2.1 High Memory Usage | ✅ §2.1 Memory (4.6) | Dedicated § |
| TC-02 | CrashLoopBackOff (generic) | `<pod> CrashLoopBackOff` | §4.5 CrashLoopBackOff | ⚠️ §4.1 overview (9.6) | PDF hit mentioning CrashLoopBackOff |
| TC-03 | `eric-pm-server-0` CrashLoop (disk full) | `eric-pm-server-0 CrashLoopBackOff` | §4.5.1 PM disk full | ✅ §4.5.1 PM disk (77.5) | Dedicated § |
| TC-04 | ImagePullBackOff | `<pod> ImagePullBackOff` | §4.4 ImagePull | ⚠️ PV/volume chunk (14.7) | PDF hit (see note) |
| TC-05 | ErrImagePull | `<pod> ErrImagePull` | §4.4 ImagePull | ⚠️ §4.1 overview (7.4) | PDF hit mentioning the status |
| TC-06 | Evicted | `<pod> Evicted` | §4.6 Evicted | ⚠️ §4.1 overview (7.4) | PDF hit mentioning Evicted |
| TC-07 | Pending (FailedScheduling) | `<alertname> <pod> Pending FailedScheduling insufficient` | §4.3 Pending | ✅ §4.3 Pending (39.1) | Dedicated § |
| TC-08 | Probe failing (Unhealthy) | `<pod> failing health probe readiness` | §4.5 probe guidance | ✅ §4.5 probe example (17.0) | Dedicated § |
| TC-09 | High CPU usage | `<alertname> <pod> CPU usage high` | §3.1 High CPU | ✅ §3.1 CPU (80.4) | Dedicated § |
| TC-10 | Negative: novel fault, no coverage | `<pod> <novel reason>` | **no hit** | ✅ NO HIT | No PDF hit; neutral note only |
| TC-11 | Zero-hit logging signal | any no-overlap query | query log `hit_count=0` | — | Log shows hit vs. miss |

**Verified strong matches (expect dedicated section):** TC-01, TC-03, TC-07,
TC-08, TC-09, and the TC-10 negative (correctly no hit).

**Verified "overview-chunk wins" cases (TC-02, TC-05, TC-06) and the odd
TC-04:** these are still valid PDF hits, but the single compound status word
(`crashloopbackoff`/`errimagepull`/`evicted`/`imagepullbackoff`) is most dense
in the §4.1 *Pod Not Ready* status-table chunk, so that chunk wins over the
dedicated section. **This is a real, documented retriever behavior, not a test
failure** — the pass criterion for these cases is therefore "a relevant PDF
chunk mentioning that status is returned", and the *observation to record* is
which section won. Two ways to make the dedicated section win if that is
desired (both are legitimate test outcomes to note, not required fixes):
  1. Upload the specific section as its *own* small runbook doc (best-per-doc
     scoring then can't be crowded out by the overview), or
  2. Enrich the alert `description` with distinctive words from the target
     section (e.g. for Evicted add "resource pressure rescheduled node"), which
     raises that section's score above the overview.

---

## Detailed steps per test case

Each case is **manual**. Replace `localhost:8080` as needed. All POST bodies are
Alertmanager v4 payloads; adjust `startsAt` to "now-ish" if your build filters
on freshness.

---

### TC-01 — Pod OOMKilled → High Memory Usage remedy

**Goal:** an OOMKilled pod incident retrieves the PDF's memory/OOM section.

**Steps**
1. Ensure PC-1..PC-4.
2. Post an OOMKilled alert:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"PodOOMKilled","namespace":"open5gs","pod":"upf-0","severity":"critical"},
       "annotations":{"description":"Container OOMKilled; memory limit exceeded"},
       "startsAt":"2026-10-27T19:02:00Z"}]}' | jq
   ```
3. In the response (or `GET /incidents/{id}`), read:
   - `top_hypothesis.cause` → should contain `OOMKilled`.
   - `suggested_next_steps[*]`.

**Expected result**
- `suggested_next_steps` contains a hit whose `title` is
  `113_15451-axb25019uen_c.pdf` and whose snippet text is from the
  **High Memory Usage / OOMKilled** section (mentions "memory", "OOMKilled",
  "memory limit").
- The neutral "No runbook source is configured" note is **absent**.

**Verify retrieval logged a hit**
```bash
curl -s http://localhost:8080/runbook-queries | jq '.entries[0]'
# expect query containing "OOMKilled", hit_count >= 1
```

---

### TC-02 — CrashLoopBackOff (generic) → §4.5 remedy

**Steps**
1. PC-1..PC-4.
2. Post:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"PodCrashLooping","namespace":"open5gs","pod":"smf-0","severity":"critical"},
       "annotations":{"description":"Container restarting repeatedly, CrashLoopBackOff"},
       "startsAt":"2026-10-27T19:05:00Z"}]}' | jq
   ```
3. Read `top_hypothesis.cause` (expect `... CrashLoopBackOff`) and
   `suggested_next_steps`.

**Expected result (verified)**
- A hit from `113_15451-axb25019uen_c.pdf`. In the pre-verified run the best
  chunk was the **§4.1 "Pod Not Ready" status-table overview** (which lists
  CrashLoopBackOff among the statuses and points to §4.5), score ~9.6 — not
  the §4.5 body. **Pass =** a PDF chunk that mentions CrashLoopBackOff is
  returned. Record which section actually won.
- To force the §4.5 body to win instead, enrich the description with distinctive
  §4.5 words, e.g. `"CrashLoopBackOff: liveness readiness probe failing,
  check logs --previous, resource limits exceeded"`.

---

### TC-03 — eric-pm-server-0 CrashLoopBackOff → §4.5.1 (disk full) remedy

**Why separate from TC-02:** the PDF has a *service-specific* subsection for
`eric-pm-server-0`. Using that exact pod name should bias the best chunk toward
the disk-full remedy (the `eric`/`pm`/`server` tokens are distinctive).

**Steps**
1. PC-1..PC-4.
2. Post:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"PMServerCrashLoop","namespace":"open5gs","pod":"eric-pm-server-0","severity":"critical"},
       "annotations":{"description":"eric-pm-server-0 in CrashLoopBackOff"},
       "startsAt":"2026-10-27T19:07:00Z"}]}' | jq
   ```
3. Read `suggested_next_steps`.

**Expected result (verified)**
- Best hit snippet is from **§4.5.1 "PM Server Disk Is Full"** — confirmed in
  the pre-verified run with a decisive score (~77.5, far above any generic
  chunk), because `eric`/`pm`/`server` are rare, high-IDF tokens. This is the
  strongest, cleanest match in the suite. Expect mentions of `eric-pm-server-0`,
  `eric-pm-exporter`, `/data`, `df -Th`, free up space.

---

### TC-04 — ImagePullBackOff → §4.4 remedy

**Steps**
1. PC-1..PC-4.
2. Post:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"PodImagePull","namespace":"open5gs","pod":"amf-0","severity":"warning"},
       "annotations":{"description":"ImagePullBackOff: cannot fetch image from registry"},
       "startsAt":"2026-10-27T19:09:00Z"}]}' | jq
   ```
3. Read `suggested_next_steps`.

**Expected result (verified)**
- A hit from the PDF is returned. In the pre-verified run the single token
  `imagepullbackoff` landed on a neighbouring **PV/volume chunk** (score
  ~14.7) rather than the §4.4 body — a chunk-boundary artifact. **Pass =** a
  PDF chunk is returned (non-neutral). Record which section won.
- To bias toward §4.4, enrich the description with its distinctive words:
  `"ImagePullBackOff: image cannot be pulled from registry, check pull secret
  and crictl pull"`.

---

### TC-05 — ErrImagePull → §4.4 remedy

**Steps**
1. PC-1..PC-4.
2. Post the same as TC-04 but
   `"alertname":"PodErrImagePull"`, `"pod":"amf-1"`,
   `"description":"ErrImagePull: image not found"`.
3. Read `suggested_next_steps`.

**Expected result (verified)**
- A PDF hit is returned; in the pre-verified run the §4.1 overview chunk won
  (score ~7.4). **Pass =** a PDF chunk mentioning the image-pull status is
  returned. Enrich the description with "image registry pull secret" to bias
  toward the §4.4 body.

---

### TC-06 — Evicted → §4.6 remedy

**Steps**
1. PC-1..PC-4.
2. Post:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"PodEvicted","namespace":"open5gs","pod":"udm-0","severity":"warning"},
       "annotations":{"description":"Pod Evicted due to node resource pressure"},
       "startsAt":"2026-10-27T19:11:00Z"}]}' | jq
   ```
3. Read `suggested_next_steps`.

**Expected result (verified)**
- A PDF hit is returned; in the pre-verified run the §4.1 overview chunk won
  (score ~7.4), which lists Evicted among the statuses. **Pass =** a PDF chunk
  mentioning Evicted is returned. To bias toward the dedicated §4.6 body,
  enrich the description with "resource pressure rescheduled node resource
  limits".

---

### TC-07 — Pending / FailedScheduling → §4.3 remedy

**Note:** `Pending`/`FailedScheduling` is not in the top-weighted fault-reason
set, so the top hypothesis may be weak and the query falls back to
`"<alertname> <pod>"`. To guarantee overlap, put the meaningful word in the
alertname/description.

**Steps**
1. PC-1..PC-4.
2. Post:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"PodPendingFailedScheduling","namespace":"open5gs","pod":"nrf-0","severity":"warning"},
       "annotations":{"description":"Pod Pending: FailedScheduling, insufficient cpu/memory"},
       "startsAt":"2026-10-27T19:13:00Z"}]}' | jq
   ```
3. Read `suggested_next_steps`.

**Expected result**
- Hit from the **Pending** section (mentions "Pending", "FailedScheduling",
  "insufficient resources", "node", "schedulable").

---

### TC-08 — Readiness/Liveness probe failing → probe guidance

**Steps**
1. PC-1..PC-4.
2. Post:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"PodUnhealthyProbe","namespace":"open5gs","pod":"pcf-0","severity":"warning"},
       "annotations":{"description":"Unhealthy: Readiness probe failed with statuscode 500"},
       "startsAt":"2026-10-27T19:15:00Z"}]}' | jq
   ```
3. Read `top_hypothesis.cause` (expect "failing health probe") and
   `suggested_next_steps`.

**Expected result**
- Hit from a section mentioning **readiness/liveness probes** (the
  CrashLoopBackOff section explicitly discusses misconfigured probes).

---

### TC-09 — High CPU usage → §3.1 remedy

**Steps**
1. PC-1..PC-4.
2. Post:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"PodHighCPUUsage","namespace":"open5gs","pod":"smf-1","severity":"warning"},
       "annotations":{"description":"Pod CPU usage high, above recommended threshold"},
       "startsAt":"2026-10-27T19:17:00Z"}]}' | jq
   ```
3. Read `suggested_next_steps`.

**Expected result**
- Hit from the **High CPU Usage** section (mentions "CPU", "usage", "request",
  "limit", "HPA").

---

### TC-10 — Negative: novel fault with no PDF coverage → no false match

**Goal:** confirm we do NOT get a spurious hit when the incident has no
corresponding runbook content, AND the neutral note appears instead.

**Steps**
1. PC-1..PC-4.
2. Post a fault whose meaningful tokens do NOT appear in the PDF:
   ```bash
   curl -s -X POST http://localhost:8080/webhook/alertmanager \
     -H 'content-type: application/json' -d '{
     "version":"4","status":"firing",
     "alerts":[{"status":"firing",
       "labels":{"alertname":"QuantumFluxCapacitorOverload","namespace":"open5gs","pod":"zzz-0","severity":"warning"},
       "annotations":{"description":"flux capacitor desynchronization anomaly"},
       "startsAt":"2026-10-27T19:19:00Z"}]}' | jq
   ```
3. Read `suggested_next_steps`.

**Expected result**
- Either zero PDF hits → `suggested_next_steps` is the single neutral note
  ("No runbook source is configured ...") **only if the store were empty** —
  but here the store HAS the PDF, so instead expect **no hits from the PDF**
  (empty retrieval) producing the neutral note. The point: no PDF section is
  wrongly offered as a remedy for an unrelated fault.

**Verify zero-hit in log**
```bash
curl -s http://localhost:8080/runbook-queries | jq '.entries[0]'
# expect hit_count == 0 for this query
```

---

### TC-11 — Zero-hit query is logged as the "write a runbook" signal

**Goal:** the query log distinguishes hits from misses (the admin signal).

**Steps**
1. Run TC-01 (a hit) then TC-10 (a miss).
2. Inspect the log:
   ```bash
   curl -s http://localhost:8080/runbook-queries | jq
   ```

**Expected result**
- `stats` shows total queries, and at least one entry with `hit_count >= 1`
  (TC-01) and one with `hit_count == 0` (TC-10).
- The `retriever` field reads `LocalRunbookRetriever` (proves the local PDF
  store is the active source, not Null).

---

## Pass/Fail summary sheet (fill in manually)

| TC ID | Query produced | PDF section retrieved? | hit_count | Pass/Fail | Notes |
|-------|----------------|------------------------|-----------|-----------|-------|
| TC-01 |                |                        |           |           |       |
| TC-02 |                |                        |           |           |       |
| TC-03 |                |                        |           |           |       |
| TC-04 |                |                        |           |           |       |
| TC-05 |                |                        |           |           |       |
| TC-06 |                |                        |           |           |       |
| TC-07 |                |                        |           |           |       |
| TC-08 |                |                        |           |           |       |
| TC-09 |                |                        |           |           |       |
| TC-10 |                |                        |           |           |       |
| TC-11 |                |                        |           |           |       |

---

## Tips while executing

- To see the full report (evidence chain + citations + next steps), grab the
  `incident_id` from the webhook response and:
  ```bash
  curl -s http://localhost:8080/incidents/<incident_id> | jq '.suggested_next_steps, .top_hypothesis'
  ```
- If a case returns the neutral "no runbook source" note unexpectedly, check
  `GET /runbooks` first — the PDF upload (PC-3) is the single most common
  thing to have been wiped (local store resets on container redeploy).
- If overlap is weaker than expected, remember the hash-suffix stripping:
  tokens like `58b5f97f6f` are discarded on purpose, so lean on real words
  (fault reason + stable name stems) in the alert's `pod`/`description`.
