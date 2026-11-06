---
name: gitops-knowledge
description: "Use when asked to explain Flux concepts or design, create, or review Flux GitOps manifests and repository patterns. Provides source-controller, reconciliation, dependency, tenancy, notification, image-automation, and delivery guidance without operating a live cluster."
---

# Flux GitOps knowledge

Adapted from `fluxcd/agent-skills`. This skill is for concepts and manifest
guidance; use `gitops-repo-audit` for a whole-repository audit and
`gitops-cluster-debug` only for an authorized live-cluster incident.

## Procedure

1. Read repository instructions and identify the installed Flux controllers and
   API versions from source evidence. Do not assume the newest API is supported.
2. Identify the source, reconciliation object, target namespace, dependencies,
   interval, timeout, pruning, health checks, service account, and tenancy
   boundary.
3. Reuse the repository's established layout and patch strategy.
4. Make ordering explicit with dependencies and health checks where consumers
   require producers to be ready.
5. Evaluate deletion and pruning consequences before recommending them.
6. Keep credentials in the approved secret mechanism and out of manifests,
   examples, logs, and generated output.
7. For Helm, Kustomize, notifications, image automation, resource sets, or
   Git-less delivery, document the controller-specific contract and failure
   signals relevant to the task.
8. Validate rendered YAML, schemas, API compatibility, and repository policy
   with existing local tools. Do not claim reconciliation without cluster
   evidence.

## Output contract

Return concept or manifest guidance with source paths, API assumptions,
resource relationships, reconciliation behavior, security and tenancy notes,
validation evidence, operational consequences, and unresolved cluster facts.

Do not contact or mutate a cluster through this skill.
