---
type: integration
title: Integrations and Data Inputs
description: External touch points - the read-only Kubernetes client, Prometheus metrics, Alertmanager, the LLM sidecar, and the service-area workbook.
tags:
  - integrations
  - kubernetes
  - prometheus
  - alertmanager
  - llm-sidecar
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-7899632fc75fcc9c19586b6f
    resource: repo://docker/SIDECAR.md
  - id: openwiki-source-a0b9c504b0887690f38d5894
    resource: repo://src/rca_agent/config.py
  - id: openwiki-source-0da4e2d3fd7447bcd91beffe
    resource: repo://src/rca_agent/impact/loader.py
  - id: openwiki-source-88f832103715fca67aef3941
    resource: repo://src/rca_agent/models/incident.py
  - id: openwiki-source-9b4953680d85f3ccfc6f695c
    resource: repo://src/rca_agent/tools/kube_client.py
  - id: openwiki-source-1e8b4f380980d8bb9b2c880b
    resource: repo://src/rca_agent/tools/query_tools.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Integrations and Data Inputs

> Draft pending subject-matter expert (SME) review.

This page describes how the agent reaches the outside world. Every integration
is read-only or advisory; none change cluster state.

## Read-only query tools

The query tools in `src/rca_agent/tools/query_tools.py` are the only way the
agent touches the cluster. The abstract `QueryTools` interface defines five
read-only methods:

- `pod_status(resource, namespace)` - phase, container statuses, restart counts,
  reasons.
- `recent_events(resource, namespace, since_minutes)` - recent Kubernetes events.
- `logs(resource, namespace, tail_lines)` - the last N log lines, treated as
  untrusted data.
- `metrics(promql, namespace)` - the result of a Prometheus Query Language
  (PromQL) query.
- `recent_changes(namespace, since_minutes)` - rollouts, ConfigMap/Secret
  updates, image changes, node/scaling events.

The module docstring is explicit that there is deliberately **no**
write/patch/delete tool - safety rests on the absence of the capability and on
Role-Based Access Control (RBAC). `StubQueryTools` returns deterministic demo
data so the whole pipeline runs with no cluster; the interface is pluggable for a
real read-only implementation.

## Kubernetes client

`src/rca_agent/tools/kube_client.py` bootstraps the read-only client. Config is
loaded one of three ways selected by `kubeconfig_mode`:

- `incluster` - use the mounted ServiceAccount token (the normal in-pod path).
- `local` - use the local kubeconfig (developer iteration).
- `auto` (default) - in-cluster if the ServiceAccount token is present, else
  fall back to kubeconfig.

The docstring states the client is used read-only: only `list_*` and `read_*`
calls are made. The `kubernetes` dependency lives in the `[cluster]` extra and
is imported lazily, so the no-cluster path never needs it installed.

## Prometheus metrics (optional)

The `metrics` tool runs PromQL queries. Metrics are optional: the
`prometheus_url` setting is `None` by default, and the configuration comment
states that when it is unset, metrics are skipped gracefully while pod status,
events, logs, and changes still work.

## Alertmanager

The `POST /webhook/alertmanager` endpoint accepts an Alertmanager payload.
Firing alerts are each reasoned about and returned as incident reports. This is
one of the two entry paths into the shared reasoning flow (see
[Workflow: Fault Detection](/openwiki/workflow-detection.md)).

## LLM sidecar (optional, loopback only)

When `reasoning_mode == "llm"`, the agent calls a local llama.cpp sidecar over
loopback to re-rank and explain hypotheses. `docker/SIDECAR.md` documents that
the sidecar serves a GGUF model, makes zero outbound calls, and is bound to
`127.0.0.1` so it is not reachable by other users even on a shared host. Any
sidecar error or timeout falls back to the deterministic extractive order, so
the LLM can never introduce a cause that lacks evidence.

## Service-area impact workbook (optional)

`src/rca_agent/impact/loader.py` parses a curated pod-to-service-area mapping
workbook. It reads two sheets - the "20-section map" (a `ServiceArea` per
numbered section with its direct pods) and the "Pod map" (per-pod component,
section, relationship, and confidence). The "Alert mapping detail" sheet is
intentionally ignored.

Pod names are matched on a **stem** - the name with the Kubernetes
replicaset/pod hash suffix stripped - so a live pod whose hash has rolled still
resolves to the workbook row (see `pod_stem` in the loader). The resulting
`ServiceAreaImpact` is additive impact context naming which service area is
affected plus redundancy counts; it is explicitly **not** a cause and never
changes hypothesis ranking (see the `service_area` field comment in
`src/rca_agent/models/incident.py`). `openpyxl` is imported lazily so a missing
dependency leaves the feature inert rather than crashing startup.

## Related pages

- [Architecture and Components](/openwiki/architecture.md)
- [Configuration Reference](/openwiki/configuration.md)
- [Workflow: Runbook Retrieval (RAG)](/openwiki/workflow-runbook-rag.md)
- [Operations and Deployment](/openwiki/operations-deploy.md)
