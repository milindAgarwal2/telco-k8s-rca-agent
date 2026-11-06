---
inclusion: always
---

# Product: Kubernetes Fault Detection & Root-Cause Agent

## Purpose and users

`k8s-rca-agent` (package `k8s-rca-agent`, `src/rca_agent/`) is a **read-only**
agent that detects faults in a Kubernetes-hosted 5G core and **explains their
likely root cause** as an incident report. It never changes the cluster — the
value is GraphRAG-style reasoning over a live dependency graph, not
remediation.

Primary users and consumers:

- **Operators** who view the dashboard and incident endpoints and upload
  runbooks (`src/rca_agent/webhook/ui.py`, `app.py`).
- **Prometheus Alertmanager**, which posts firing alerts to the webhook.
- Optional: a **local LLM sidecar** (rerank/explain) and a **Prometheus**
  metrics endpoint.

## Primary capabilities and observable outcomes

The pipeline is `detect → gather evidence → reason → report`
(`src/rca_agent/reasoning/extractive.py`). The output is an **incident report**,
not an action, containing: the symptom, ranked root-cause hypotheses with an
evidence chain, blast radius (downstream dependents from the graph), suggested
next steps for a human (via runbook RAG), and citations for every claim.

Two fault inputs feed one reasoning pipeline:

- Alertmanager webhook (`POST /webhook/alertmanager`, firing alerts only).
- A background Kubernetes event/status watcher
  (`src/rca_agent/detection/event_watcher.py`).

## In-scope responsibilities

- Build and refresh an in-memory NetworkX dependency graph of **one
  application in one namespace**.
- Deterministically gather evidence, walk the graph, correlate recent changes,
  and rank candidate causes (the six-step extractive pipeline).
- Optionally re-rank and explain causes with a local LLM, falling back
  transparently to the deterministic order.
- Serve a server-rendered dashboard and read-only query/graph endpoints.
- Scoped service-area impact mapping and an offline accuracy eval harness.

## Out-of-scope responsibilities

- Any cluster mutation or remediation — none exists by construction.
- The monitored 5G core workloads, the external Prometheus/Alertmanager stack,
  and the LLM sidecar implementation itself.
- The many planning/notes documents and binary artifacts at the repository root
  (`PLAN*.md`, `*.pptx`, `*.docx`, `*.xlsx`) are not part of the running
  service.

## Domain concepts and terminology

- **NF / UPF / SMF / PFCP** — 5G core Network Functions and protocol.
- **Anchor** — the stable entity a fault is attributed to: service > owning
  workload > pod (`graph/dependency_graph.py::anchor_of`).
- **Blast radius** — downstream dependents of the affected resource.
- **`calls` edge** — a cited dependency inferred only from literal env/ConfigMap
  values matching a service name; the graph deliberately has **no** speculative
  NF-to-NF topology.
- **Correlation** — a pattern flag linking different anchors with the same
  failure signature; it never claims a specific shared cause.
- **Extractive mode** — deterministic, no-LLM reasoning (the default).

## Externally visible interfaces and operational modes

- HTTP API and dashboard served from a single FastAPI process
  (`rca_agent.webhook.app:app`, console script `rca-agent`). Key endpoints
  include `/healthz`, `/readyz`, `/graph/*`, `/incidents`,
  `/webhook/alertmanager`, `/runbooks`, and `/debug/detection`.
- Modes (env `RCA_*`): `reasoning_mode` = `extractive` (default) or `llm`;
  `cluster_enabled` = `false` (demo/stub data) or `true` (read-only kube
  client). Defaults run out-of-the-box with no cluster and no LLM.

## Business and compatibility constraints (evidence-backed)

- **Safety is enforced by the platform, not the prompt:** no write tool exists,
  and the Helm `ClusterRole` grants only `get`/`list`/`watch`.
- **Rules first, LLM second:** the LLM may only reorder and explain
  deterministic candidates; it can never invent a cause.
- **Untrusted input:** log lines and alert text are fenced as data before
  reaching the LLM (prompt-injection defense).
- Consumes the Alertmanager **v4** payload schema (`models/alert.py`).

## Known variants, feature controls, unresolved questions

- Optional dependency extras gate features and degrade gracefully when absent:
  `llm`, `cluster`, `viz`, `rag`, `rag-semantic`, `pptx`.
- Semantic runbook RAG is opt-in and only active with its deps **and** a live
  LLM sidecar; otherwise it falls back to TF-IDF.
- Unresolved (maintainer review): the HTTP runbook retriever is a declared
  **TODO** (unbuilt); runtime LLM-mode and real-cluster behavior are **not**
  exercised by the offline test suite; metrics/tracing export for the agent
  itself is not present; `secrets` read access in the `ClusterRole` should be
  confirmed acceptable even though code never reads secret values.

## Documentation status

Generated documentation under `knowledge-base/` and `openwiki/` remains a
**draft** until reviewed. Treat current source, schemas, and tests as
authoritative over any generated summary.
