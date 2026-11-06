---
type: workflow
title: Workflow - Fault Detection
description: How faults become incidents via the Alertmanager webhook and the automatic event/status watcher sharing one entry point and timeline.
tags:
  - detection
  - alertmanager
  - event-watcher
  - workflow
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-a0b9c504b0887690f38d5894
    resource: repo://src/rca_agent/config.py
  - id: openwiki-source-1c84a5c88eb780bf72e79fd5
    resource: repo://src/rca_agent/detection/event_watcher.py
  - id: openwiki-source-6bc88d380e5a869a73acc6c4
    resource: repo://src/rca_agent/models/alert.py
  - id: openwiki-source-91386c0b169bf4a09d4c43b0
    resource: repo://src/rca_agent/webhook/app.py
  - id: openwiki-source-28ae127d14a9e73ad2bfdc74
    resource: repo://tests/test_event_watcher.py
  - id: openwiki-source-b77afb5f14c6c713d8cff181
    resource: repo://tests/test_webhook.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Workflow: Fault Detection

> Draft pending subject-matter expert (SME) review.

A fault becomes an incident through one of two paths. Both feed the same
`ReasoningFlow` entry point and record into the same incident timeline, so a
manually posted alert and an auto-detected fault are handled identically from
that point on.

## Path 1: the Alertmanager webhook

`POST /webhook/alertmanager` in `src/rca_agent/webhook/app.py` accepts an
Alertmanager payload (`AlertmanagerPayload` in `src/rca_agent/models/alert.py`).
The handler keeps only alerts whose `status` is `firing`, runs each through
`ReasoningFlow.run`, and records every resulting report in the event watcher's
incident pool via `record_external_incident`. The `Alert` model derives its
`target` resource from labels in priority order (pod, then deployment,
statefulset, service, job, instance).

`tests/test_webhook.py` verifies this path end to end: posting the sample
payload returns a report with a symptom, ranked hypotheses, and suggested next
steps, and a manually posted incident shows up in the incidents list.

## Path 2: the automatic event/status watcher

The event watcher (`src/rca_agent/detection/event_watcher.py`) polls the
read-only Kubernetes client and raises incidents without a human crafting a
payload. Its design is deliberately conservative:

- **Fault-reason filtering.** Only the named fault reasons in
  `KubeEvent.FAULT_REASONS` (CrashLoopBackOff, OOMKilled, ImagePullBackOff,
  ErrImagePull, FailedScheduling, Unhealthy, FailedMount, NodeNotReady,
  Evicted) are acted on, not every Warning event, so transient noise does not
  create incidents.
- **Scope to graph nodes.** Only events whose involved object names a node
  already present in the current dependency graph are acted on, reusing the
  graph builder's namespace and selector scoping.
- **Dedup by UID.** A Kubernetes event keeps one stable identifier while it
  recurs, so the watcher remembers identifiers already turned into an incident
  and does not re-diagnose a long-lived fault every poll cycle; the seen-set is
  bounded.
- **Staleness window.** Events older than `event_max_age_minutes` are dropped.

## Status-based detection

Independent of fresh events, the graph rolls up each pod's health on every
rebuild. A pod that stays unhealthy across `status_unhealthy_rebuilds`
consecutive rebuilds is raised as an incident even when no fresh event exists,
so the agent survives Kubernetes aging events out from under a still-broken pod.
Setting `status_unhealthy_rebuilds` to 0 disables status-based detection. This
is described in the setting comments in `src/rca_agent/config.py`.

## Correlation across incidents

Incidents sharing an identical failure signature on a different resource within
`incident_correlation_window_minutes` are linked via `related_incidents`. As the
event watcher's `_correlate` and `PLAN.md` make clear, this is a pattern flag
only - it never names or ranks a shared cause. See
[Concept: Service Anchoring and Incident Model](/openwiki/concepts-service-anchoring.md).

## Self-diagnosis: /debug/detection

The `GET /debug/detection` endpoint in `src/rca_agent/webhook/app.py` exposes
every gate in the watcher's last poll cycle so that "no incidents" is
self-diagnosing. Its counters include `events_seen`, `events_403` (event list
forbidden), `matched_fault_reason`, `dropped_stale`, `out_of_scope`,
`already_seen`, `event_incidents`, `status_incidents`, and `unhealthy_pods`,
alongside the current detection settings.

## Verification

`tests/test_event_watcher.py` verifies the watcher behavior and
`tests/test_webhook.py` verifies the webhook path, including that both share one
incident timeline.

## Related pages

- [Architecture and Components](/openwiki/architecture.md)
- [Reasoning: Extractive Pipeline and LLM Rerank](/openwiki/reasoning-pipeline.md)
- [Concept: Service Anchoring and Incident Model](/openwiki/concepts-service-anchoring.md)
- [Operations and Deployment](/openwiki/operations-deploy.md)
