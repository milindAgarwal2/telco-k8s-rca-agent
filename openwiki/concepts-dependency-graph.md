---
type: concept
title: Concept - The Dependency Graph
description: The in-memory NetworkX dependency graph, its node and edge kinds, health roll-up, calls-edge detection, and the demo fallback.
tags:
  - dependency-graph
  - networkx
  - kubernetes
  - health
  - concept
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-0cba96084ad97a9c0edf32a9
    resource: repo://src/rca_agent/graph/builder.py
  - id: openwiki-source-cf0a2b2e5577a3db98230eef
    resource: repo://src/rca_agent/graph/dependency_graph.py
  - id: openwiki-source-502c5a8ec75087e62a5f761a
    resource: repo://tests/test_cluster_graph.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Concept: The Dependency Graph

> Draft pending subject-matter expert (SME) review. Direct evidence and
> inference are labelled separately below.

The dependency graph is the structural backbone the agent reasons over. It is a
live, timestamped, directed multigraph of one network function (NF) application
in one namespace, backed by the NetworkX library. "NF" means a 5G core network
function such as the User Plane Function (UPF) or Session Management Function
(SMF).

The graph and its builder live in `src/rca_agent/graph/`.

## Node kinds

Node kinds are defined by the `NodeKind` enum in
`src/rca_agent/graph/dependency_graph.py`:

- `network_function` - a workload treated as an NF.
- `service` - a Kubernetes Service.
- `pod` - a running pod.
- `node` - a Kubernetes worker node.
- `configmap`, `secret`, `pvc` - configuration, secret, and persistent-volume-
  claim resources a pod mounts.
- `deployment`, `replicaset` - the workload and its revision.

## Edge kinds

Edge kinds are defined by the `EdgeKind` enum in the same file:

- `calls` - A depends on B, so B is upstream of A and a candidate cause of A's
  failure.
- `runs_on` - a pod runs on a node.
- `mounts` - a pod mounts a ConfigMap, Secret, or persistent volume claim.
- `managed_by` - a pod is managed by a ReplicaSet or Deployment.
- `selects` - a Service selects a pod.

The direction of a `calls` edge is meaningful: `A --calls--> B` means B is
upstream of A, which is how the reasoning step separates candidate causes from
blast radius.

## Health roll-up

Each node carries a rolled-up health state from the `Health` enum: `healthy`,
`degraded`, `down`, or `unknown`. For a workload (NF) node, `roll_up_health`
derives the state from the pods reachable via `managed_by` edges:

- all pods healthy -> `healthy`
- no pods healthy -> `down`
- a mix -> `degraded`
- no pods or no information -> `unknown`

This is documented in the `Health` enum docstring and implemented by
`roll_up_health` in `src/rca_agent/graph/dependency_graph.py`.

Every node and edge also carries change timestamps (`changed_at`), so the agent
can reconstruct what the graph looked like when a fault started. Graph mutation
is done only by the builders, never by the LLM; the mutation methods carry an
explicit comment to that effect.

## How calls edges are derived (not guessed)

*Direct evidence from the builder header comment in
`src/rca_agent/graph/builder.py`:* the project deliberately does **not** fabricate
NF-to-NF topology. There is no authoritative static service map for this stack,
and OpenTelemetry (OTel) tracing is not stood up on someone else's cluster. So
`calls` edges are derived from the one grounded signal available through
read-only get/list: a container's literal environment-variable values and the
values of ConfigMaps it mounts or reads via `envFrom`, scanned for a DNS-boundary
match against another Service's name already in the graph.

A pod configured with an address that names another Service gets a cited `calls`
edge to that Service; a pod with no such reference gets none. Absence of a match
means absence of an edge, not a guess.

## The demo graph fallback

When `cluster_enabled` is `False` (the default), `GraphBuilder.rebuild` returns
a built-in demo graph instead of talking to a cluster, so the rest of the system
runs with no cluster. This is implemented in `GraphBuilder.rebuild` in
`src/rca_agent/graph/builder.py`.

## Verification

The cluster-free tests in `tests/test_cluster_graph.py` build the graph from a
fake Kubernetes client and assert that pods, nodes, and the workload are
discovered with the expected node kinds, and that `runs_on`, `managed_by`, and
`mounts` edges are created.

## Related pages

- [Architecture and Components](/openwiki/architecture.md)
- [Concept: Service Anchoring and Incident Model](/openwiki/concepts-service-anchoring.md)
- [Reasoning: Extractive Pipeline and LLM Rerank](/openwiki/reasoning-pipeline.md)
- [Glossary](/openwiki/glossary.md)
