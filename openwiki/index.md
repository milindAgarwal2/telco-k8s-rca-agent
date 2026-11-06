---
okf_version: "0.2"
---

# Files

- [Architecture and Components](architecture.md) - How the Kubernetes root-cause agent's subsystems fit together inside one FastAPI process.
- [Change-Impact Navigation with Folder Specs](change-impact-navigation.md) - How to use the folder SPECS.md files and the specification relationship map to bound the impact of a contract change before editing, then verify declared relationships against source.
- [Concept - The Dependency Graph](concepts-dependency-graph.md) - The in-memory NetworkX dependency graph, its node and edge kinds, health roll-up, calls-edge detection, and the demo fallback.
- [Concept - Service Anchoring and the Incident Model](concepts-service-anchoring.md) - The incident report schema, service-anchored resolution, blast radius vs upstream causes, the incident lifecycle state machine, anchor dedup, and correlation.
- [Concurrency, State Ownership, and Resource Lifetime](concurrency-state-ownership.md) - The background tasks, which component owns each piece of mutable state, how the dependency graph is swapped atomically, how in-memory stores are bounded, and the one unresolved locking question.
- [Configuration Reference](configuration.md) - Environment-driven settings (RCA_ prefix) controlling reasoning mode, cluster access, graph, detection, RAG, LLM, and incident capture.
- [Glossary](glossary.md) - Plain-English definitions of the domain and technical terms used across this wiki, grounded in the repository.
- [Integrations and Data Inputs](integrations.md) - External touch points - the read-only Kubernetes client, Prometheus metrics, Alertmanager, the LLM sidecar, and the service-area workbook.
- [Operations and Deployment](operations-deploy.md) - The container image, Helm chart with read-only RBAC, health probes, release packaging, and the optional LLM sidecar deploy.
- [System Overview](overview.md) - What the Kubernetes root-cause agent does, its read-only safety stance, and the detect-gather-reason-report flow.
- [Quickstart](quickstart.md) - Minimal steps to run the agent locally with no cluster and no LLM, post a sample alert, and route to the right deep-dive page.
- [Reasoning - Extractive Pipeline and LLM Rerank](reasoning-pipeline.md) - The rules-first deterministic reasoning steps, the concrete scoring weights, the change-to-fault linkage, the optional LLM rerank sidecar, and the guardrails that keep results grounded.
- [Request Lifecycle and Representation Transitions](request-lifecycle.md) - Follow one fault from input to incident report, naming which object represents it and which component owns it at each stage - Alert, ReasoningState, and IncidentReport.
- [Testing and Evaluation](testing.md) - The pytest unit suite and the offline fault-injection harness that measures top-2 accuracy.
- [Unresolved Questions and Known Gaps](unresolved-questions.md) - Inferred, deployment-specific, stale, and unresolved findings - including the LangGraph-versus-flow gap, a duplicate function definition, a locking question, and version skew - collected for subject-matter expert review.
- [Workflow - Fault Detection](workflow-detection.md) - How faults become incidents via the Alertmanager webhook and the automatic event/status watcher sharing one entry point and timeline.
- [Workflow - Runbook Retrieval (RAG)](workflow-runbook-rag.md) - How suggested next steps are retrieved from runbooks via the local and optional semantic retrievers, with the query log.
