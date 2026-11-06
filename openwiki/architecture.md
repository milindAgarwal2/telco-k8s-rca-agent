---
type: architecture
title: Architecture and Components
description: How the Kubernetes root-cause agent's subsystems fit together inside one FastAPI process.
tags:
  - architecture
  - components
  - fastapi
  - dependency-graph
  - reasoning
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-1c84a5c88eb780bf72e79fd5
    resource: repo://src/rca_agent/detection/event_watcher.py
  - id: openwiki-source-0cba96084ad97a9c0edf32a9
    resource: repo://src/rca_agent/graph/builder.py
  - id: openwiki-source-c16433f8e6e340fdc8a2595d
    resource: repo://src/rca_agent/reasoning/flow.py
  - id: openwiki-source-91386c0b169bf4a09d4c43b0
    resource: repo://src/rca_agent/webhook/app.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Architecture and Components

> Draft pending subject-matter expert (SME) review. Statements below are drawn
> directly from repository source unless clearly labelled as inference.

This page maps the major subsystems of the Kubernetes Root-Cause Analysis (RCA)
agent and how they connect. RCA means working out *why* a fault happened. The
whole system runs as a single process: one FastAPI web application that also
serves a server-rendered dashboard.

## Package layout

All application code lives under `src/rca_agent/`. Each package owns one
responsibility:

| Package | Responsibility |
| --- | --- |
| `config` | Environment-driven settings (prefix `RCA_`), with defaults that run out of the box in no-LLM, no-cluster mode. |
| `webhook` | The FastAPI application, HTTP endpoints, and the server-rendered dashboard. |
| `detection` | Automatic fault detection: the Kubernetes event/status watcher. |
| `graph` | The in-memory NetworkX dependency graph, its builder, and HTML visualization. |
| `tools` | Read-only query tools over cluster state (pod status, events, logs, metrics, changes). |
| `reasoning` | The deterministic extractive pipeline plus the optional Large Language Model (LLM) rerank step. |
| `models` | Pydantic schemas for the incoming alert and the outgoing incident report. |
| `rag` | Runbook retrieval (Retrieval-Augmented Generation) for human-facing next steps. |
| `impact` | The curated pod-to-service-area mapping used for impact context. |
| `eval` | The fault-injection accuracy harness. |

The `README.md` "Repository layout" section describes this same structure, and
the directories are present under `src/rca_agent/`.

## The single-process model

The application builds its dependency graph once and reuses it across requests.
`src/rca_agent/webhook/app.py` creates a module-level `GraphBuilder`, and when
no cluster is configured it builds the demo graph eagerly at import so every
endpoint (and the test client) sees a populated graph. A background refresh
loop then rebuilds the graph on a fixed interval; `GraphBuilder.rebuild` swaps
its internal graph atomically, so read endpoints never observe a half-built
graph.

The application lifespan starts three background tasks: the initial graph
build, the periodic refresh loop, and the event-watch loop. When a cluster is
enabled, the initial build runs in a background thread so it does not block
uvicorn from serving `/healthz` while a large namespace is walked. This is
stated in the lifespan and startup comments in `src/rca_agent/webhook/app.py`.

## Two ways in, one reasoning entry point

There are two sources of incidents, and they share a single reasoning entry
point and a single incident timeline:

1. **Alertmanager webhook.** `POST /webhook/alertmanager` takes a firing alert
   payload. Each firing alert is passed to `ReasoningFlow.run`, and the
   resulting report is recorded in the event watcher's incident pool via
   `record_external_incident`.
2. **Automatic detection.** The event watcher polls the cluster for fault-signal
   Kubernetes events and feeds any recognized fault through the *same*
   `ReasoningFlow` entry point. This is documented in the module docstring of
   `src/rca_agent/detection/event_watcher.py`.

`ReasoningFlow` (`src/rca_agent/reasoning/flow.py`) is the shared entry point.
It runs the deterministic extractive pipeline, then optionally asks the local
LLM sidecar to re-rank and explain the result when `reasoning_mode == "llm"`.

Because both paths record into the same `EventWatcher.incidents` store, a
manually posted alert and an auto-detected fault appear on one timeline and
participate in the same correlation pool. This is described in the
`event_watcher.py` docstring and implemented by `record_external_incident`.

## How evidence flows

*Inference, grounded in the source:* the dependency graph is the structural
backbone. The reasoning steps in `src/rca_agent/reasoning/steps.py` gather
evidence from the read-only query tools and walk the graph to find upstream
candidate causes and the downstream blast radius. The graph builder derives the
graph from native Kubernetes objects only, with no traces or static call map
(see `src/rca_agent/graph/builder.py`).

## Related pages

- [System Overview](/openwiki/overview.md)
- [Concept: The Dependency Graph](/openwiki/concepts-dependency-graph.md)
- [Reasoning: Extractive Pipeline and LLM Rerank](/openwiki/reasoning-pipeline.md)
- [Workflow: Fault Detection](/openwiki/workflow-detection.md)
- [Integrations and Data Inputs](/openwiki/integrations.md)
