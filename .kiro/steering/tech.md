---
inclusion: always
---

# Technology and conventions

## Languages, runtimes, build

- **Python**, `requires-python >= 3.10` (`pyproject.toml`). The container and
  the documented `.venv` use **Python 3.12** (`Dockerfile`, `Makefile`).
- **Build system:** setuptools (`pyproject.toml`, `build-backend =
  "setuptools.build_meta"`), `src/` package discovery, console script
  `rca-agent = rca_agent.webhook.app:main`.
- **Lint/format:** ruff (line length 100, target `py310`).
- **Tests:** pytest (`pythonpath = ["src"]`, `testpaths = ["tests"]`).

## Core frameworks and libraries

- **FastAPI** + **uvicorn[standard]** — single long-running web process.
- **pydantic** / **pydantic-settings** — models and `RCA_`-prefixed settings.
- **networkx** — in-memory dependency graph (`MultiDiGraph`).
- **httpx** — LLM sidecar / Prometheus HTTP calls.
- **jinja2** + vendored Bootstrap/HTMX — server-rendered dashboard.
- **openpyxl** — service-area workbook parsing.

Optional extras (feature-gated, degrade gracefully when missing):
`llm` (langgraph/langchain-core), `cluster` (kubernetes client), `viz` (pyvis),
`rag` (pymupdf4llm/pymupdf/pypdf), `rag-semantic` (fastembed/chromadb/langchain
splitters, in-memory ChromaDB — no on-disk sqlite), `pptx` (python-pptx),
`dev` (pytest/ruff).

## Documented development and validation commands

Run via the project venv (`Makefile` uses `.venv/bin/python`):

- `make check` — ruff + pytest (the pre-commit gate).
- `make test`, `make lint`, `make fmt`.
- `make eval` — offline fault-injection accuracy harness
  (`python -m rca_agent.eval`), gated on top-2 accuracy (default 0.80), can
  fail CI.
- `make install` — editable install with `dev,cluster,viz,rag,pptx` extras.
- Quick start: `pip install -e .` then
  `uvicorn rca_agent.webhook.app:app --reload --port 8080` (see `README.md`).

## Configuration sources and environment variables

All configuration is environment-driven (prefix `RCA_`) via pydantic-settings,
with an optional `.env` file (`src/rca_agent/config.py`). Defaults run in
extractive, no-cluster mode. Key variable names (no secret values here):

- Service: `RCA_HOST`, `RCA_PORT`, `RCA_LOG_LEVEL`.
- Reasoning: `RCA_REASONING_MODE` (`extractive`|`llm`).
- Cluster: `RCA_CLUSTER_ENABLED`, `RCA_KUBECONFIG_MODE`
  (`auto`|`incluster`|`local`), `RCA_NAMESPACE`, `RCA_NF_SELECTOR`.
- Graph / detection: `RCA_GRAPH_REBUILD_INTERVAL_SECONDS`,
  `RCA_EVENT_WATCH_*`, `RCA_EVENT_MAX_AGE_MINUTES`,
  `RCA_STATUS_DETECTION_ENABLED`, `RCA_STATUS_UNHEALTHY_REBUILDS`,
  `RCA_INCIDENT_CORRELATION_WINDOW_MINUTES`.
- Evidence / sources: `RCA_LOG_TAIL_LINES`,
  `RCA_CHANGE_CORRELATION_WINDOW_MINUTES`, `RCA_PROMETHEUS_URL`.
- RAG: `RCA_RUNBOOK_RAG_URL` (HTTP retriever, **unbuilt TODO**),
  `RCA_RUNBOOK_STORE_PATH`, `RCA_RUNBOOK_ASSET_DIR`,
  `RCA_RUNBOOK_RAG_SEMANTIC`, `RCA_RUNBOOK_RAG_EMBED_MODEL`.
- Impact: `RCA_SERVICE_AREA_MAP_PATH`.
- LLM sidecar: `RCA_LLM_PROVIDER`, `RCA_LLM_MODEL`, `RCA_LLM_BASE_URL`
  (loopback `127.0.0.1:8090` by default), `RCA_LLM_TIMEOUT_SECONDS`,
  `RCA_LLM_MAX_TOKENS`, `RCA_LLM_TEMPERATURE`.
- Capture (off by default, **sensitive** when on): `RCA_INCIDENT_CAPTURE_PATH`
  and related `RCA_INCIDENT_CAPTURE_*`.

The Helm chart maps only a subset to container env (`RCA_PORT`,
`RCA_REASONING_MODE`, `RCA_CLUSTER_ENABLED`, `RCA_NAMESPACE`, `RCA_LOG_LEVEL`,
`RCA_RUNBOOK_RAG_URL`).

## Runtime topology, persistence, protocols, external systems

- **Topology:** one FastAPI/uvicorn process with three background asyncio tasks
  (initial cluster build in a thread, periodic graph refresh with atomic swap,
  event-watch loop). No multiprocessing.
- **Persistence:** all operational state is **in-memory or local disk** — there
  is no external database. Graph, incident pool (bounded 200), and seen-event
  UIDs are in-memory; the runbook store is local JSON + extracted images under
  `/tmp` (wiped on redeploy, `emptyDir`); the semantic index is in-memory only.
- **External systems (all optional / deployment-dependent):** Kubernetes API
  (read-only `get`/`list`/`watch`), Prometheus (`/api/v1/query`), and the LLM
  sidecar (OpenAI-compatible `/v1/chat/completions`, probed via `/health` then
  `/v1/models`) over loopback.

## Platform, version, and deployment constraints

- Container: `python:3.12-slim`, installs `.[cluster,viz,rag,rag-semantic,pptx]`,
  runs as non-root uid 10001 with `readOnlyRootFilesystem`,
  `allowPrivilegeEscalation: false`, and dropped capabilities; single uvicorn
  process via `docker/entrypoint.sh`. The embedding model is pre-cached in the
  image.
- Deployment: Helm chart with read-only RBAC, Deployment (liveness `/healthz`,
  readiness `/readyz`, writable `/tmp` `emptyDir`), and a Service.

## Testing layers and special infrastructure

Offline-first: the suite uses a **fake kube client** (`tests/fake_kube.py`,
`eval/fake_cluster.py`) and a mocked sidecar — **real cluster and real LLM
behavior are not exercised**. Layers: unit/pipeline, webhook/interface,
detection, RAG, LLM-rerank guardrails, impact, eval harness, and ASCII-safety.
No live infrastructure is required to run `make check`.

## Security and operational boundaries

- Read-only by construction: no write/patch/delete tool; `ClusterRole` grants
  only `get`/`list`/`watch` (plus `metrics.k8s.io` `get`/`list`).
- Prompt-injection defense: untrusted log/alert text is fenced before the LLM;
  LLM output is validated as a permutation of given hypothesis ids or the
  original order is kept.
- LLM sidecar is loopback-only; secret **values** are never read even though
  secret existence is recorded for `mounts` edges.
- Observability: standard `logging` under `rca_agent*`; `/debug/detection`
  exposes per-cycle gate counters. No metrics/tracing exporter for the agent
  itself is present.

## Maintainer-review assumptions (environment-specific)

- The HTTP runbook retriever is a declared TODO; setting `RCA_RUNBOOK_RAG_URL`
  alone does nothing yet.
- RBAC enforcement, network policy, and sidecar isolation are
  deployment-dependent and cannot be proven from the repository.
- Capacity/performance figures are not documented — do not invent them.
- Git operations in this workspace must run through Git Bash per
  `.kiro/steering/aide-git-operations.md`.
