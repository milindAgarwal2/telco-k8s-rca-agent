# Implementation Map: Code Reduction via AIDE Components + Alert -> Service-Area Endpoint

| Field | Value |
|-------|-------|
| Document type | Implementation map (planning artifact; no code changes) |
| Current commit | `2f4774f` |
| Date | 2026-11-03 |
| Status | Draft until maintainer review |
| Evidence base | `src/rca_agent/**/SPECS.md`, `knowledge-base/` HLD/LLD, read source modules, `.kiro/` + `.aide/` component inventory |

Authority notice: repository source and tests remain authoritative. This map
proposes changes but makes none. Every claim about existing behaviour is traced
to a source file; proposals are labelled as proposals. No application code,
tests, config, or the AIDE overlay were modified to produce this map.

---

## Part A - Can existing agents / hooks / MCP servers reduce the codebase?

### A.1 What "existing components" actually exist here

The workspace ships the AIDE overlay (an ownership boundary that is NOT part of
the target application). Inventory from `.kiro/settings/mcp.json`,
`.kiro/agents/`, `.kiro/hooks/`, and `.aide/full/mcp-servers/`:

| Component | Kind | Relevant capability | Evidence |
|-----------|------|--------------------|----------|
| `aide-kubernetes-mcp` | MCP server (enabled) | Read-only kubectl: status, verify context, list workloads, list networking, list events, read one resource projection, read pod logs | `.aide/full/mcp-servers/aide-kubernetes-mcp/src/aide_kubernetes_mcp/server.py` |
| `aide-kubernetes-observer` | Agent | Drives the Kubernetes MCP for bounded read-only evidence | `.kiro/agents/aide-kubernetes-observer.json` |
| `aide-knowledge-mcp` | MCP server (enabled) | Read-only lexical retrieval over `knowledge-base/` + `openwiki/` with citations | `.aide/full/mcp-servers/aide-knowledge-mcp/README.md` |
| `aide-kubernetes-change-mcp` | MCP server (disabled) | Change/plan workflow (write path) | `.kiro/settings/mcp.json` (`"disabled": true`) |
| `neo4j`, `graphiti`, `memory`, `postgres` | MCP servers | Knowledge-graph / memory / DB access | `.kiro/settings/mcp.json` |

### A.2 The critical boundary: MCP servers are Kiro-time tools, not a runtime library

This is the single most important finding and it bounds every proposal below.

- The AIDE MCP servers run as **Kiro assistant tools over stdio** (`uv run ... aide-kubernetes-mcp`, `transport="stdio"`). They are invoked by the agent during a Kiro session.
- The RCA agent is a **standalone deployed service** - a single `uvicorn` process (`rca_agent.webhook.app:app`) running in-cluster from a Helm chart (evidence: `src/rca_agent/webhook/SPECS.md` sections 1 and 6; `docker/`, `deploy/helm/`).
- A deployed FastAPI pod cannot call a developer-workstation MCP stdio server at runtime. The AIDE overlay is also explicitly excluded from the application (ownership boundary in `.aide/managed-files.json`).

Conclusion: the AIDE MCP servers **cannot be dropped into the running agent to delete runtime code**. They can reduce *developer/operational effort*, not shipped application line count. Treat "reduce the size of the code" in two honest buckets below.

### A.3 Bucket 1 - Realistic reductions (recommended)

These remove or shrink code without weakening the read-only safety model or the
deployed-service architecture.

| # | Candidate to reduce | Current source (evidence) | Proposal | Est. effect | Risk |
|---|---------------------|---------------------------|----------|-------------|------|
| R1 | Workstation cluster inspection during dev/debug | `tools/kube_client.py` is a thin read-only bootstrap; ad-hoc debugging often adds throwaway scripts | Use `@aide-kubernetes-observer` + `aide-kubernetes-mcp` for interactive cluster look-ups instead of writing/keeping debug scripts | Removes incidental debug code; no runtime delta | Low |
| R2 | Knowledge/doc lookup glue | `rag/` local retriever is for runbooks surfaced to users at runtime (keep it) | For *developer* knowledge search over `knowledge-base/`, use `aide-knowledge-mcp` rather than new tooling | No runtime delta; avoids new dev tooling | Low |
| R3 | `kube_client.py` loader branching | `tools/kube_client.py` `_load_config` hand-rolls auto/incluster/local | Optional: lean on `kubernetes.config.load_config()` (library helper) to collapse branches | ~20-30 lines | Low-Med (behaviour parity must be tested) |

R1 and R2 are the safe, immediate wins: they cut *process/tooling* overhead, which is the practical meaning of "reuse existing components" in this workspace.

### A.4 Bucket 2 - Tempting but NOT recommended

| # | Idea | Why it looks attractive | Why to reject (evidence) |
|---|------|------------------------|--------------------------|
| X1 | Replace the agent's runtime `tools/kube_client.py` + `QueryTools` with `aide-kubernetes-mcp` | Both are read-only kubectl; looks like duplicate code | The MCP is a Kiro stdio tool, not importable into the deployed pod (A.2). Would couple a shipped service to the dev-time AIDE overlay, which is an excluded boundary. Breaks the single-process deploy model (`webhook/SPECS.md`). |
| X2 | Move reasoning onto `aide-operations-investigator` / observer agents | Agents already "investigate" | Those agents run in a Kiro session with a human in the loop; the RCA agent must run unattended in-cluster on every Alertmanager webhook. Different execution model. |
| X3 | Use `neo4j`/`graphiti` MCP instead of the in-process NetworkX graph | Graph DB vs in-memory graph | `graph/SPECS.md`: the graph is rebuilt live from the cluster every 60s in-process with timestamped history; an external stdio MCP cannot serve the deployed pod and adds infra the POC deliberately avoids (`PLAN.md` "no new infra"). |

Net: the honest answer is that **runtime code cannot be meaningfully deleted by
adopting the AIDE MCP servers**, because they are assistant-time tools and the
agent is a deployed service. The real reuse value is in **development and
operations workflows** (R1, R2).

---

## Part B - Expose a service: alert in -> service-area mapping out

### B.1 What exists today (evidence)

- Service-area lookup is self-contained and cluster-free:
  `load_service_area_index(path)` -> `ServiceAreaIndex.by_pod(pod_name)` -> `ServiceAreaImpact`
  (`src/rca_agent/impact/index.py`, `models.py`).
- `ServiceAreaImpact` carries `mapped`, `component`, `service_area`, `section`,
  `relationship_type`, `confidence`, `component_sibling_count`,
  `service_area_pod_count`, and `summary_line()` (`impact/models.py`).
- Today it is only reachable **embedded in a full incident**: `steps.build_service_area`
  attaches it during the reasoning pipeline, surfaced inside `IncidentReport.service_area`
  and the PPTX export. There is **no direct alert-in -> service-area-out endpoint**
  (verified: the only POST on alerts is `/webhook/alertmanager`, which runs the
  entire reasoning flow - `webhook/app.py`).
- An alert already knows its target resource: `Alert.target` resolves the pod by
  the fixed label priority `pod > deployment > statefulset > service > job > instance`
  (`models/SPECS.md` 5.1, `models/alert.py`).

Gap: there is no lightweight way to send an alert (or a pod name) and get just
the service-area answer without running graph walk, change correlation, and
optional LLM re-rank.

### B.2 Proposed endpoint (design only - not implemented)

Add one read-only POST endpoint on the existing FastAPI app. No new process, no
cluster access, no new dependency (openpyxl is already core per `impact/SPECS.md`).

- Route: `POST /service-area`
- Input (either shape; reuse existing models, add nothing new to the wire):
  - an Alertmanager v4 body (`AlertmanagerPayload`) - reuse `Alert.target` to get the pod, OR
  - a minimal `{ "pod": "<name>" }` body for direct lookups.
- Behaviour:
  1. Resolve the pod name (from `alert.target` or the `pod` field).
  2. `idx = load_service_area_index(settings.service_area_map_path)`.
  3. If `idx is None` -> feature inert: return `mapped=false` with a clear "service-area map not configured" note (mirrors existing inert behaviour in `index.py`).
  4. `impact = idx.by_pod(pod)`; return `impact` (already a Pydantic model -> JSON) plus `impact.summary_line()`.
- Output: the existing `ServiceAreaImpact` serialized, e.g.
  `{ pod, mapped, component, service_area, section, relationship_type, confidence, component_sibling_count, service_area_pod_count, summary }`.
- Invariants preserved (from `impact/SPECS.md`): read-only, deterministic,
  UNKNOWN-never-guessed, cited curated data, never changes hypothesis ranking,
  inert when unconfigured. No Kubernetes write capability is added.

### B.3 Why this is cheap and safe

- Reuses `impact/` wholesale; the endpoint is thin glue (resolve pod -> call
  `by_pod` -> return model). Estimated ~25-40 lines in `webhook/app.py`.
- No new model needed if you accept `AlertmanagerPayload` and/or a tiny inline
  `{pod}` body; optionally add a `ServiceAreaRequest` model in `models/` for a
  clean contract.
- Cluster-free: unlike `/webhook/alertmanager`, this path never builds the graph
  or calls the LLM, so it works in the base install with only a workbook present.
- Caching: `load_service_area_index` is cheap but re-reads the xlsx; the pipeline
  already resolves it per incident on purpose (so a re-uploaded map takes effect).
  Match that behaviour, or cache behind `functools.lru_cache` keyed on path+mtime
  if latency matters (proposal, measure first).

### B.4 Change-set preview (files that WOULD change - none changed now)

| File | Change | Reason |
|------|--------|--------|
| `src/rca_agent/webhook/app.py` | Add `@app.post("/service-area")` handler | The new endpoint |
| `src/rca_agent/models/alert.py` (optional) | Add `ServiceAreaRequest` `{pod}` model | Clean direct-lookup contract |
| `tests/test_gui_service_area.py` or new `tests/test_service_area_endpoint.py` | Add endpoint tests (mapped / unmapped / unconfigured) | Prove AC1-AC3 from `impact/SPECS.md` |
| `src/rca_agent/webhook/SPECS.md` + `src/rca_agent/impact/SPECS.md` | Record the new endpoint contract | Spec-driven protocol (section 12 of each) |
| `K8s_Root-Cause_Agent_POC_Plan.pptx` (optional) | Note the standalone endpoint on the service-area slide | Keep deck current |

### B.5 Acceptance scenarios (Given/When/Then)

- SA-EP-AC1 (valid/mapped): Given a configured workbook and an alert whose
  `target` is a mapped pod, When `POST /service-area`, Then `mapped=true` with
  component, section, confidence, and both pod counts.
- SA-EP-AC2 (unmapped): Given a pod not in the workbook, When posted, Then
  `mapped=false` and the summary reports UNKNOWN (never guessed).
- SA-EP-AC3 (unconfigured): Given `RCA_SERVICE_AREA_MAP_PATH` unset/missing,
  When posted, Then the endpoint returns a clear "feature inert" response and
  does not error (mirrors `load_service_area_index` returning None).
- SA-EP-AC4 (read-only/no ranking effect): Given any input, When handled, Then
  no cluster call and no hypothesis ranking occur (impact stays context-only).

---

## Part C - Recommendation summary

1. Code reduction: adopt R1 (use `aide-kubernetes-observer`/`aide-kubernetes-mcp`
   for dev/debug cluster look-ups) and R2 (`aide-knowledge-mcp` for dev knowledge
   search). Optionally simplify `kube_client.py` loader (R3) with a tested parity
   check. Do NOT wire AIDE MCP servers into the deployed runtime (X1-X3).
2. New service: add a thin, cluster-free `POST /service-area` endpoint that
   reuses `impact/` to turn an alert (or pod name) into a `ServiceAreaImpact`,
   preserving every documented impact invariant.

## Unknowns and review items

- MCP runtime reachability from the deployed pod is assumed unavailable based on
  the stdio transport and the AIDE ownership boundary; a maintainer should
  confirm no in-cluster MCP gateway is planned.
- `kube_client.py` R3 simplification needs a behaviour-parity test for the
  auto/incluster/local matrix before adoption.
- Endpoint input shape (Alertmanager payload vs minimal `{pod}` vs both) is a
  maintainer decision; B.2 proposes supporting both.
- Whether to cache the loaded index (B.3) should be decided after measuring xlsx
  load latency against expected request volume.