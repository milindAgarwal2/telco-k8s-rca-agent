---
type: glossary
title: Glossary
description: Plain-English definitions of the domain and technical terms used across this wiki, grounded in the repository.
tags:
  - glossary
  - terminology
  - acronyms
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-7899632fc75fcc9c19586b6f
    resource: repo://docker/SIDECAR.md
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-a0b9c504b0887690f38d5894
    resource: repo://src/rca_agent/config.py
  - id: openwiki-source-cf0a2b2e5577a3db98230eef
    resource: repo://src/rca_agent/graph/dependency_graph.py
  - id: openwiki-source-88f832103715fca67aef3941
    resource: repo://src/rca_agent/models/incident.py
  - id: openwiki-source-8990877acd61b533651868cc
    resource: repo://src/rca_agent/rag/runbook_retriever.py
  - id: openwiki-source-1e8b4f380980d8bb9b2c880b
    resource: repo://src/rca_agent/tools/query_tools.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Glossary

> Draft pending subject-matter expert (SME) review. Each term is defined as it
> is used in this repository.

**RCA (Root-Cause Analysis).** Working out *why* a fault happened. The project
is a read-only agent that detects faults and explains their root cause rather
than fixing them. See `README.md`.

**5G core.** The set of Kubernetes-hosted network functions the agent monitors.
The default monitored namespace is `open5gs`. See `README.md` and the
`namespace` default in `src/rca_agent/config.py`.

**NF (Network Function).** A component of the 5G core, such as the UPF or SMF,
modeled as a workload node in the dependency graph. See
`src/rca_agent/graph/dependency_graph.py`.

**UPF (User Plane Function).** A 5G core network function. It appears as the
headline example (a UPF pod OOMKilled after a ConfigMap memory-limit change) in
`README.md` and the demo query tools in `src/rca_agent/tools/query_tools.py`.

**SMF (Session Management Function).** A 5G core network function that, in the
headline example, shows errors caused upstream by the UPF being unreachable.
See `README.md`.

**RBAC (Role-Based Access Control).** The Kubernetes mechanism that grants the
agent's ServiceAccount only `get`, `list`, and `watch` permissions, so even if
the model tried a write, Kubernetes would refuse it. See `README.md`.

**RAG (Retrieval-Augmented Generation).** Here, retrieving human-facing
remediation guidance from uploaded runbooks and surfacing it as suggested next
steps. See `src/rca_agent/rag/runbook_retriever.py`.

**LLM (Large Language Model).** An optional component that only re-ranks and
explains the rule-gathered hypotheses; it can never invent a cause. Used only
when `reasoning_mode == "llm"`. See `src/rca_agent/config.py` and
`docker/SIDECAR.md`.

**GGUF.** The on-disk model file format served by the local llama.cpp sidecar
(for example a Qwen2.5-1.5B model). The GGUF file lives outside the images and
is mounted read-only. See `docker/SIDECAR.md`.

**PromQL (Prometheus Query Language).** The query language used by the optional
metrics tool; a metric citation records the PromQL query. See the `Citation`
model in `src/rca_agent/models/incident.py` and the `metrics` tool in
`src/rca_agent/tools/query_tools.py`.

**Blast radius.** The affected downstream services, read from the graph - the
impact side of the graph walk. It is the `blast_radius` field on the incident
report. See `src/rca_agent/models/incident.py`.

**Anchor.** The stable entity a fault is attributed to, resolved as service,
else owning workload, else pod. Recorded as `affected_anchor` and `anchor_kind`.
See `src/rca_agent/models/incident.py`.

**Extractive mode.** The default deterministic reasoning mode: no LLM,
reproducible and cheap, outputting ranked candidates and the evidence table.
See `reasoning_mode` in `src/rca_agent/config.py` and `README.md`.

**calls edge.** A graph edge meaning "A depends on B" (B is upstream of A and a
candidate cause of A's failure). It is derived only from grounded configuration
signals, never guessed. See `src/rca_agent/graph/dependency_graph.py` and
`src/rca_agent/graph/builder.py`.

## Related pages

- [System Overview](/openwiki/overview.md)
- [Concept: The Dependency Graph](/openwiki/concepts-dependency-graph.md)
- [Reasoning: Extractive Pipeline and LLM Rerank](/openwiki/reasoning-pipeline.md)
