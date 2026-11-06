---
type: unresolved
title: Unresolved Questions and Known Gaps
description: Inferred, deployment-specific, stale, and unresolved findings - including the LangGraph-versus-flow gap, a duplicate function definition, a locking question, and version skew - collected for subject-matter expert review.
tags:
  - unresolved
  - known-issues
  - gaps
  - review
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T20:42:17.288Z
sources:
  - id: openwiki-source-8c766a70a756519f31be9429
    resource: repo://deploy/helm/Chart.yaml
  - id: openwiki-source-f056d81349e383de297943d9
    resource: repo://deploy/helm/values.yaml
  - id: openwiki-source-7899632fc75fcc9c19586b6f
    resource: repo://docker/SIDECAR.md
  - id: openwiki-source-31c5d408b8f1718dfd9d4e59
    resource: repo://PLAN.md
  - id: openwiki-source-72d490f7547de9b6443afd3a
    resource: repo://src/rca_agent/__init__.py
  - id: openwiki-source-a0b9c504b0887690f38d5894
    resource: repo://src/rca_agent/config.py
  - id: openwiki-source-1c84a5c88eb780bf72e79fd5
    resource: repo://src/rca_agent/detection/event_watcher.py
  - id: openwiki-source-0cba96084ad97a9c0edf32a9
    resource: repo://src/rca_agent/graph/builder.py
  - id: openwiki-source-8990877acd61b533651868cc
    resource: repo://src/rca_agent/rag/runbook_retriever.py
  - id: openwiki-source-c16433f8e6e340fdc8a2595d
    resource: repo://src/rca_agent/reasoning/flow.py
  - id: openwiki-source-2adad82f3d59c8880d77ad59
    resource: repo://src/rca_agent/reasoning/state.py
  - id: openwiki-source-10b8d638a6c6b84a80abd837
    resource: repo://src/rca_agent/reasoning/steps.py
generated: { by: "kiro", at: "2026-11-03T20:42:17.288Z" }
---

# Unresolved Questions and Known Gaps

> Draft pending subject-matter expert (SME) review. This page separates direct
> repository evidence from inference and lists open questions a reviewer should
> resolve.

## Known gaps grounded in the repository

### No authoritative NF-to-NF topology; correlation is the only cross-incident link

*Direct evidence, `PLAN.md` "Known Issues" and
`src/rca_agent/detection/event_watcher.py`:* real network-function (NF) to NF
topology needs either a maintained static service map (no authoritative source
exists for this stack) or OpenTelemetry (OTel) tracing (new infrastructure not
stood up on someone else's cluster). So the project does not build such edges.
Instead, `_correlate` in the event watcher links incidents that share an
identical failure signature on a different resource within the correlation
window. `PLAN.md` is explicit that this links incidents but never claims or
ranks a specific shared cause, and that the real fix - naming *which* dependency
is shared - still needs real topology data.

### calls edges exist but depend on literal references

*Direct evidence, `src/rca_agent/graph/builder.py` and `PLAN.md`:* `calls` edges
are built only from literal environment-variable or ConfigMap references to
another Service name. `PLAN.md` records that whether this fires on a specific
outage depends on whether the real pods reference their shared dependency by
literal name; when a dependency is reached via a Secret-only reference, a
hardcoded address, or service discovery that never appears as literal text, no
edge is built, which `PLAN.md` describes as the honest, non-fabricated outcome
rather than a bug.

### The HTTP runbook retriever is not built

*Direct evidence, `src/rca_agent/rag/runbook_retriever.py` and
`src/rca_agent/config.py`:* the `HttpRunbookRetriever` for an external
doc-intelligence service is still unbuilt; setting `runbook_rag_url` alone does
nothing yet. Only the `LocalRunbookRetriever` is functional today.

### Observability prerequisites marked to-build in the plan

*Direct evidence, `PLAN.md`:* several environment pieces are marked to-build,
including the `kind`/`k3d` cluster with Open5GS, the observability stack
(`kube-prometheus-stack`, Loki, OpenTelemetry/Jaeger), and Alertmanager rules.
A reviewer should confirm which of these exist in the target environment, since
latency and error-rate paths that depend on them are not covered by the event
watcher alone.

## Verified code and documentation observations

These are confirmed against current source. They are recorded for owner
confirmation and are **not** asserted as defects.

### The "LangGraph flow" is a documentation gap

*Direct evidence, `src/rca_agent/reasoning/flow.py`:* `ReasoningFlow` is a plain
Python class that runs the extractive pipeline and, when `reasoning_mode ==
"llm"`, calls an HTTP rerank. There is no LangGraph graph object in the read
source. However, `src/rca_agent/reasoning/state.py` and
`src/rca_agent/reasoning/steps.py` docstrings describe the steps as
"LangGraph-compatible" / usable "as LangGraph nodes", and the `[llm]` optional
extra lists LangGraph dependencies. A reviewer from the reasoning area should
confirm whether LangGraph is still intended or the docstrings and extra are
stale.

### Duplicate `_signature` definition in the event watcher

*Direct evidence, `src/rca_agent/detection/event_watcher.py`:* the module
defines a function named `_signature` **twice**. The second definition - the
anchor/pod-aware version that blanks the resource, anchor, and each affected pod
name out of the top hypothesis - shadows the first at import time, so the first
definition is dead code. A reviewer from the detection area should confirm the
intended version and whether the first should be removed.

### Unlocked EventWatcher shared state

*Direct evidence, `src/rca_agent/detection/event_watcher.py`:*
`EventWatcher.incidents` and its streak/latch dicts are mutated from the
event-watch worker thread and read from request handlers without an explicit
lock. Whether a lock is warranted under load is an open question; see
[Concurrency, State Ownership, and Resource Lifetime](concurrency-state-ownership.md)
for the full context. The detection owner should confirm.

### Version skew between the package and the Helm chart

*Direct evidence:* the Python package version is `0.10.1`
(`src/rca_agent/__init__.py`), while the Helm chart declares `version: 0.1.0`
and `appVersion: "0.1.0"` (`deploy/helm/Chart.yaml`) and the default container
image is `tag: "0.3.9"` (`deploy/helm/values.yaml`). These three version strings
disagree. A release/deployment reviewer should confirm the intended release
image and chart version. **Review required.**

## Deployment-specific details not verifiable from source

The following come from narrative documentation (`docker/SIDECAR.md`) and
describe a specific environment. They cannot be confirmed from repository source
and should be treated as deployment-specific:

- The GGUF model file location and the one-time copy to a jumpserver host.
- The specific jumpserver address and the `deploy-cobra.sh` operational flow.
- Whether the LLM sidecar is actually deployed in any given environment.

## Inference (clearly labelled)

- *Inference:* because the default settings disable the cluster and the LLM, a
  freshly cloned repository most likely exercises only the demo graph and the
  extractive path until an operator opts in. This follows from the defaults in
  `src/rca_agent/config.py` but is not asserted as runtime fact.
- *Inference:* the `PLAN.md` Known Issues narrative references dated
  real-cluster test observations (for example the `eric-pc-sm-*` outage). These
  are historical notes and may be stale relative to the current code; a reviewer
  should re-validate them against the live environment.

## Open questions for SMEs

1. Is an authoritative NF-to-NF service map or OTel tracing available in the
   target environment to replace the correlation-only workaround?
2. Which observability components (Prometheus, Loki, Alertmanager rules) are
   deployed, and should metric-dependent paths be documented as active?
3. Is the LLM sidecar deployed, and what GGUF model and host are canonical?
4. Are the dated `PLAN.md` findings still accurate against the current cluster?
5. Is LangGraph still intended for the reasoning flow, or are the
   LangGraph references in the docstrings and the `[llm]` extra stale?
6. Which `_signature` definition in the event watcher is intended, and should
   the shadowed first definition be removed?
7. Should `EventWatcher`'s shared state be protected by an explicit lock?
8. Which version string is canonical for a release: the package `0.10.1`, the
   chart `0.1.0`, or the image tag `0.3.9`?

## Related pages

- [Concept: The Dependency Graph](concepts-dependency-graph.md)
- [Reasoning: Extractive Pipeline and LLM Rerank](reasoning-pipeline.md)
- [Concurrency, State Ownership, and Resource Lifetime](concurrency-state-ownership.md)
- [Workflow: Fault Detection](workflow-detection.md)
- [Operations and Deployment](operations-deploy.md)
