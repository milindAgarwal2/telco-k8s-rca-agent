# Kubernetes Fault Detection & Root-Cause Agent (POC)

A **read-only** agent that detects faults in a Kubernetes-hosted 5G core and
**explains their root cause** — it never changes the cluster. The value is in
GraphRAG-style reasoning over a live dependency graph, not in remediation.

```
detect  →  gather evidence  →  reason  →  report
```

The output is an **incident report**, not an action:

- **Symptom** — what fired, where, and when.
- **Ranked root-cause hypotheses** — each with a confidence level and an
  evidence chain, e.g.
  `SMF errors ← UPF unreachable ← UPF pod OOMKilled ← memory limit lowered in a ConfigMap at 14:02`.
- **Blast radius** — affected downstream services, read from the graph.
- **Suggested next steps** — pulled from runbooks via RAG, for a human only.
- **Citations** — every claim links to a log line, metric, event or runbook.

## Safety: read-only by construction

Safety is enforced by the **platform, not the prompt**:

- **RBAC** — the ServiceAccount gets a ClusterRole with only `get`, `list`,
  `watch`. Even if the LLM tries a write, Kubernetes refuses it.
- **Query-only tools** — no write tool exists to call.
- **Untrusted input** — logs and alert text are fenced as data (prompt-injection
  defense), since a log line can carry injected instructions.

## Rules first, LLM second

Deterministic code collects evidence and finds candidate causes; the LLM only
**ranks and explains** them. This keeps results reproducible, cheap and hard to
hallucinate. An **extractive no-LLM mode** (the default) still outputs the
ranked candidates and the evidence table.

## Repository layout

```
src/rca_agent/
  config.py                # settings (env-driven)
  webhook/                 # FastAPI app: Alertmanager webhook + health + incidents
  detection/               # automatic fault detection: K8s event watcher
  graph/                   # NetworkX live dependency graph (timestamped)
  tools/                   # read-only query tools (pods, events, logs, metrics)
  reasoning/               # LangGraph flow + extractive no-LLM fallback
  models/                  # incident report & alert schemas
  rag/                     # runbook retriever interface (existing doc pipeline)
streamlit_app/             # Streamlit dashboard: Graph / Incidents / Health tabs
docker/                    # entrypoint.sh (starts FastAPI + Streamlit) + Dockerfile support
deploy/helm/               # Helm chart: read-only SA/ClusterRole, Deployment, Service
tests/                     # unit tests
PLAN.md                    # phase-by-phase roadmap (4 weekly phases)
```

## Quick start (no cluster, no LLM)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # core deps only
uvicorn rca_agent.webhook.app:app --reload --port 8080
# POST a sample Alertmanager payload:
curl -X POST localhost:8080/webhook/alertmanager \
  -H 'content-type: application/json' \
  -d @tests/fixtures/alertmanager_sample.json
```

Optional extras: `pip install -e '.[llm]'` (LangGraph), `'.[cluster]'`
(kubernetes client), `'.[dev]'` (pytest/ruff).

## Status

POC scaffold. See [`PLAN.md`](PLAN.md) for the 4-week roadmap. Ranked root
causes without an LLM by week 2; baseline comparison in week 4.
