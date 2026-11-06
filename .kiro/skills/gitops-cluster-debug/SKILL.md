---
name: gitops-cluster-debug
description: "Use only for an explicitly authorized live Flux troubleshooting request when flux-operator-mcp is already configured and available. Collects fresh reconciliation evidence, diagnoses the smallest fault domain, and verifies recovery without silently adding or switching integrations."
---

# Flux live-cluster debugging

Adapted from `fluxcd/agent-skills`. This is a conditional skill. Start with
`gitops-knowledge` or `gitops-repo-audit`; activate this skill only when live
Flux state is required and `flux-operator-mcp` is already approved, configured,
and reachable.

## Hard prerequisites

- explicit cluster context and namespace or tenant scope;
- explicit authorization for live inspection;
- available `flux-operator-mcp` integration;
- repository or source revision expected to reconcile;
- separate approval before any mutation or reconciliation trigger.

If any prerequisite is absent, stop safely. Do not install a server, fall back
to another cluster tool, or select a different cluster automatically.

## Workflow

1. Confirm target identity and collect timestamped Flux controller and custom
   resource status.
2. Trace source artifact to Kustomization or HelmRelease, dependencies, applied
   resources, health checks, and controller logs or events.
3. Compare desired repository revision with observed artifact and last attempted
   revision.
4. Separate observations, hypotheses, and historical evidence.
5. Identify the smallest fault domain: source fetch, authentication,
   decryption, build, dependency, apply, health check, Helm action, policy, or
   target workload.
6. Propose the least disruptive correction at the GitOps source whenever
   practical, with impact and rollback.
7. After approval and action, verify source readiness, reconciliation, applied
   revision, dependent readiness, and the original workload symptom.

## Output contract

Return target, timestamps, observed revisions, reconciliation graph,
observations, hypotheses, evidence, correction status, verification, rollback,
and unresolved risk. Redact secret data and avoid broad log collection.
