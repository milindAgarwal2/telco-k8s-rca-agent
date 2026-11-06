---
type: workflow
title: Reasoning - Extractive Pipeline and LLM Rerank
description: The rules-first deterministic reasoning steps, the concrete scoring weights, the change-to-fault linkage, the optional LLM rerank sidecar, and the guardrails that keep results grounded.
tags:
  - reasoning
  - extractive
  - scoring
  - llm-rerank
  - guardrails
  - prompt-injection
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T20:42:17.288Z
sources:
  - id: openwiki-source-7899632fc75fcc9c19586b6f
    resource: repo://docker/SIDECAR.md
  - id: openwiki-source-e31c229491def7f7fd85c018
    resource: repo://src/rca_agent/reasoning/extractive.py
  - id: openwiki-source-c16433f8e6e340fdc8a2595d
    resource: repo://src/rca_agent/reasoning/flow.py
  - id: openwiki-source-7ffc997b9bcd51cabf4affe0
    resource: repo://src/rca_agent/reasoning/llm_rerank.py
  - id: openwiki-source-10b8d638a6c6b84a80abd837
    resource: repo://src/rca_agent/reasoning/steps.py
  - id: openwiki-source-ec4de8c11fb00f109dd22d51
    resource: repo://tests/test_reasoning.py
generated: { by: "kiro", at: "2026-11-03T20:42:17.288Z" }
---

# Reasoning: Extractive Pipeline and LLM Rerank

> Draft pending subject-matter expert (SME) review.

Reasoning is rules-first and Large Language Model (LLM)-second. The deterministic
extractive pipeline gathers and scores evidence; the optional LLM only re-ranks
and explains what the rules produced. The entry point is `ReasoningFlow` in
`src/rca_agent/reasoning/flow.py`.

## The extractive pipeline

`ExtractivePipeline.run` in `src/rca_agent/reasoning/extractive.py` runs the
deterministic steps in order and assembles an `IncidentReport`. This is the
default mode: reproducible, cheap, and hard to hallucinate. The steps (functions
in `src/rca_agent/reasoning/steps.py`) run in this order:

1. `triage` - identify the affected resource and the fault time window from the
   alert.
2. `gather_evidence` - collect pod status, recent Kubernetes events, a log tail,
   and error lines through the read-only query tools.
3. `graph_walk` - resolve the service anchor and walk the dependency graph for
   upstream candidate causes and the downstream blast radius.
4. `change_correlation` - correlate recent changes within the configured window.
5. `hypothesize_and_rank` - form and rank candidate root-cause hypotheses.
6. `build_next_steps` - retrieve runbook-derived suggested next steps.

A final `build_service_area` step attaches optional service-area impact context.
The retriever and service-area index are resolved fresh per incident so a runbook
or mapping uploaded after startup takes effect on the next incident.

## Deterministic scoring weights

`hypothesize_and_rank` in `src/rca_agent/reasoning/steps.py` scores each
candidate cause with fixed additive weights (no LLM is involved):

| Signal | Weight |
| --- | --- |
| A fault event on the resource (OOMKilled, CrashLoopBackOff, ImagePullBackOff, ErrImagePull, Evicted) | +0.45 |
| A readiness/liveness probe failure | +0.50 |
| A recent change the affected pod actually consumes (correlated) | +0.30 |
| A recent change the pod does **not** mount (uncorrelated) | +0.05 |
| An unhealthy upstream dependency (cascade) | +0.20 |
| Error/fatal log lines present (applied to every candidate) | +0.15 |

A correlated change that links to a fault on the same pod adds a further +0.10
bonus (see below). Each hypothesis's confidence is then clamped to a maximum of
0.99. Hypotheses are sorted by confidence, highest first.

The much lower +0.05 weight for an uncorrelated change is deliberate: unrelated
namespace churn can never outrank the actual fault, but it is still surfaced so
no real signal is hidden.

## Linking a change to a fault

`_link_change_to_fault` in `src/rca_agent/reasoning/steps.py` models the
project's headline example - a ConfigMap memory-limit change leading to an
`OOMKilled` pod. When a **correlated** change (one the affected pod actually
mounts) and a fault hypothesis both reference the affected pod, the two are
chained into a single causal hypothesis: the change's evidence chain is appended
to the fault, and the fault gains the +0.10 bonus. An uncorrelated change is
never chained into the fault, so only a change the pod genuinely consumes
becomes part of the causal story.

## No fabricated causes

Every hypothesis's evidence chain is prefixed with
`symptom: <alertname> on <resource>`, and a hypothesis is only ever created when
it is tied to gathered evidence - the scoring code builds candidates from the
evidence it collected, never from an empty guess. `tests/test_reasoning.py`
asserts this by checking that a report carries citations and that a UPF
`OOMKilled` event combined with a ConfigMap change outranks other candidates.

## The service-area step is impact only

The final `build_service_area` step attaches the affected pod's service area as
**scoped impact context**. It never creates a hypothesis and never changes any
hypothesis's ranking; when the feature is off or the pod is unmapped, it is a
no-op and no area is fabricated.

## Prompt-injection fencing

Untrusted text (log lines, alert annotations) is fenced as data before it is
ever shown to a model. The `fence` helper in `src/rca_agent/reasoning/steps.py`
wraps such text in explicit `<<UNTRUSTED_DATA>>` delimiters, and the LLM rerank
module in `src/rca_agent/reasoning/llm_rerank.py` applies its own
`<<UNTRUSTED_EVIDENCE>>` fence and instructs the model not to follow any
instruction found inside the evidence text.

## LLM rerank: reorder and explain only

When `reasoning_mode == "llm"`, `ReasoningFlow` calls
`src/rca_agent/reasoning/llm_rerank.py`. The module docstring states the LLM may
do only two things: reorder the existing hypotheses by their stable index, and
write a one-line explanation for each. The hard guardrails, enforced in code,
are:

- the LLM may reference only hypothesis indices it was given; any unknown,
  duplicate, or missing index is rejected and the original order is kept;
- the LLM cannot add, remove, or invent a cause - the code only reorders the
  existing `Hypothesis` objects and optionally attaches an explanation;
- untrusted log text is fenced before the model sees it; and
- any error, timeout, or unavailable sidecar returns the report unchanged in the
  extractive order.

So enabling the LLM can never break reasoning or change *which* causes exist -
only their order and a short explanation.

## The local llama.cpp sidecar

The LLM runs as a local llama.cpp sidecar serving a GGUF model (for example
Qwen2.5-1.5B), reached over loopback with an OpenAI-compatible Application
Programming Interface (API). `docker/SIDECAR.md` states it makes zero outbound
calls and is bound to `127.0.0.1` so it is not reachable by other users even on
a shared host. Full deployment details are on the
[Operations and Deployment](operations-deploy.md) page.

## Verification

`tests/test_reasoning.py` exercises the extractive pipeline against the demo
graph, asserting that a UPF OOMKilled event combined with a ConfigMap change
outranks other candidates, and checks the demo graph's edges and health
roll-up.

## Related pages

- [Architecture and Components](architecture.md)
- [Concept: Service Anchoring and the Incident Model](concepts-service-anchoring.md)
- [Request Lifecycle and Representation Transitions](request-lifecycle.md)
- [Workflow: Runbook Retrieval (RAG)](workflow-runbook-rag.md)
- [Integrations and Data Inputs](integrations.md)
