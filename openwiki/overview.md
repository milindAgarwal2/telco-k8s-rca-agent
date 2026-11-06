---
type: overview
title: System Overview
description: What the Kubernetes root-cause agent does, its read-only safety stance, and the detect-gather-reason-report flow.
tags:
  - overview
  - rca
  - kubernetes
  - 5g-core
  - read-only
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-05ccef8d4cf1698187f20464
    resource: repo://pyproject.toml
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-91386c0b169bf4a09d4c43b0
    resource: repo://src/rca_agent/webhook/app.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# System Overview

> Draft pending subject-matter expert (SME) review.

## What this system does

This repository is a read-only agent that detects faults in a Kubernetes-hosted
5G core and **explains their root cause**. "RCA" stands for Root-Cause Analysis
- working out *why* a fault happened. The agent never changes the cluster; its
value is reasoning over a live dependency graph, not remediation. This purpose
is stated in `README.md` and the package description in `pyproject.toml`.

The cluster hosts 5G core network functions. A "network function" (NF) is a
component of the 5G core, such as the User Plane Function or Session Management
Function.

## The four-stage flow

`README.md` describes the pipeline as:

```
detect  ->  gather evidence  ->  reason  ->  report
```

1. **Detect** - a fault is noticed, either from an Alertmanager webhook or by the
   automatic event/status watcher.
2. **Gather evidence** - deterministic code collects pod status, Kubernetes
   events, log tails, metrics, and recent changes through read-only tools.
3. **Reason** - rules first score candidate causes; an optional Large Language
   Model (LLM) only re-ranks and explains them.
4. **Report** - the agent emits an incident report.

## The output: an incident report, not an action

The output is an incident report, not an action. Per `README.md`, it contains:

- a **symptom** - what fired, where, and when;
- **ranked root-cause hypotheses**, each with a confidence level and an evidence
  chain;
- a **blast radius** - affected downstream services, read from the graph;
- **suggested next steps** - pulled from runbooks via Retrieval-Augmented
  Generation (RAG), for a human only; and
- **citations** - every claim links to a log line, metric, event, or runbook.

## Read-only by construction

Safety is enforced by the platform, not the prompt. `README.md` describes three
layers:

- **RBAC** - the ServiceAccount receives a ClusterRole with only `get`, `list`,
  and `watch`, so even if the LLM tried a write, Kubernetes would refuse it.
- **Query-only tools** - no write tool exists to call.
- **Untrusted input** - logs and alert text are fenced as data, defending
  against prompt injection, because a log line can carry injected instructions.

The whole service runs as one FastAPI process (see
`src/rca_agent/webhook/app.py`), which also serves a server-rendered dashboard.

## Rules first, LLM second

Deterministic code collects evidence and finds candidate causes; the LLM only
ranks and explains them. This keeps results reproducible, cheap, and hard to
hallucinate, and the default extractive no-LLM mode still outputs the ranked
candidates and the evidence table.

## Where to go next

- [Quickstart](/openwiki/quickstart.md) - run it locally with no cluster.
- [Architecture and Components](/openwiki/architecture.md) - the subsystem map.
- [Concept: The Dependency Graph](/openwiki/concepts-dependency-graph.md) - the
  structural backbone.
- [Reasoning: Extractive Pipeline and LLM Rerank](/openwiki/reasoning-pipeline.md)
  - how causes are ranked and explained.
