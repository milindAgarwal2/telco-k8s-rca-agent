---
type: quickstart
title: Quickstart
description: Minimal steps to run the agent locally with no cluster and no LLM, post a sample alert, and route to the right deep-dive page.
tags:
  - quickstart
  - setup
  - local
  - getting-started
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T20:42:17.288Z
sources:
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
  - id: openwiki-source-05ccef8d4cf1698187f20464
    resource: repo://pyproject.toml
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-a0b9c504b0887690f38d5894
    resource: repo://src/rca_agent/config.py
  - id: openwiki-source-c1ea7a3ab989e419273e93a9
    resource: repo://tests/fixtures/alertmanager_sample.json
generated: { by: "kiro", at: "2026-11-03T20:42:17.288Z" }
---

# Quickstart

> Draft pending subject-matter expert (SME) review.

This page gets the agent running locally with no Kubernetes cluster and no Large
Language Model (LLM). The commands are taken from `README.md`.

## Run it (no cluster, no LLM)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # core deps only
uvicorn rca_agent.webhook.app:app --reload --port 8080
```

The agent starts in its default mode: `reasoning_mode = "extractive"` (no LLM,
deterministic) and `cluster_enabled = False` (the in-memory demo graph). This is
confirmed by the defaults in `src/rca_agent/config.py`.

## Post a sample alert

With the server running, post the sample Alertmanager payload bundled in the
repository (`tests/fixtures/alertmanager_sample.json`):

```bash
curl -X POST localhost:8080/webhook/alertmanager \
  -H 'content-type: application/json' \
  -d @tests/fixtures/alertmanager_sample.json
```

The response is an incident report with a symptom, ranked hypotheses, and
suggested next steps.

## Optional extras

`pyproject.toml` defines optional dependency groups, installed as, for example,
`pip install -e '.[llm]'`:

- `llm` - LangGraph and LangChain core for the LLM rerank path.
- `cluster` - the Kubernetes client for live read-only cluster access.
- `viz` - pyvis for the interactive graph visualization.
- `rag` - structure-aware runbook extraction (pymupdf4llm, pymupdf, pypdf).
- `rag-semantic` - the opt-in semantic runbook retriever (fastembed, chromadb,
  langchain splitters).
- `pptx` - per-incident report export (python-pptx).
- `dev` - pytest, ruff, and related developer tools.

The core agent runs in no-LLM extractive mode without any of these.

## Developer loop

From the `Makefile` (which uses the `.venv` interpreter):

- `make test` - run the full pytest suite.
- `make lint` - Ruff static checks.
- `make check` - lint plus test (the pre-commit gate).
- `make eval` - run the fault-injection accuracy harness.

See [Testing and Evaluation](testing.md) for details, and `INSTALL.md` for a
fuller installation walkthrough.

## Where to go next (task routing)

Pick the page that matches your question:

- **What does it do and how is it structured?** -
  [System Overview](overview.md) and [Architecture and Components](architecture.md).
- **How is a fault turned into a report?** - follow one fault end to end in
  [Request Lifecycle and Representation Transitions](request-lifecycle.md), then
  see how causes are scored in
  [Reasoning: Extractive Pipeline and LLM Rerank](reasoning-pipeline.md).
- **How are faults detected?** - [Workflow: Fault Detection](workflow-detection.md).
- **Who owns the graph, incidents, and other mutable state, and is it
  thread-safe?** -
  [Concurrency, State Ownership, and Resource Lifetime](concurrency-state-ownership.md).
- **What might a change break?** -
  [Change-Impact Navigation with Folder Specs](change-impact-navigation.md).
- **How do I configure or deploy it?** - [Configuration Reference](configuration.md)
  and [Operations and Deployment](operations-deploy.md).
- **What is still uncertain or needs review?** -
  [Unresolved Questions and Known Gaps](unresolved-questions.md).

## Related pages

- [System Overview](overview.md)
- [Configuration Reference](configuration.md)
- [Operations and Deployment](operations-deploy.md)
- [Testing and Evaluation](testing.md)
- [Request Lifecycle and Representation Transitions](request-lifecycle.md)
- [Concurrency, State Ownership, and Resource Lifetime](concurrency-state-ownership.md)
- [Change-Impact Navigation with Folder Specs](change-impact-navigation.md)
