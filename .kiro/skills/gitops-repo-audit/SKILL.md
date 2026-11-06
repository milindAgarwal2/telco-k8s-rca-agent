---
name: gitops-repo-audit
description: "Use when asked to audit or assess a Flux GitOps repository for structure, schema validity, API compatibility, security, tenancy, dependency, pruning, and operational readiness. Performs repository analysis without requiring live-cluster access."
---

# Flux GitOps repository audit

Adapted from `fluxcd/agent-skills`. Audit repository evidence first; do not turn
an audit request into a live-cluster investigation.

## Audit workflow

1. Define repository revision, paths, environments, and exclusions.
2. Inventory Flux sources, reconciliation objects, Helm releases,
   kustomizations, notifications, image automation, service accounts, secrets
   references, and environment overlays.
3. Map reconciliation dependencies, namespaces, source references, and pruning
   boundaries. Identify cycles, missing producers, and orphaned overlays.
4. Validate YAML, Kustomize or Helm rendering, schemas, and API compatibility
   using existing repository tools and the versions declared by the repository.
5. Review remote references, mutable tags, secret exposure, cross-namespace
   access, impersonation, tenancy, permissions, and unsafe decryption or
   substitution patterns.
6. Review timeouts, retry and suspend behavior, health checks, observability,
   rollback or revert path, disaster recovery, and operator usability.
7. Separate confirmed defects from risks requiring cluster evidence.

## Output contract

Lead with prioritized, source-linked findings. Then provide:

- revision and audit scope;
- repository and reconciliation relationship map;
- validation commands and results;
- API and schema compatibility status;
- security, tenancy, pruning, and dependency assessment;
- operational-readiness gaps;
- checks not run and live evidence still needed.

Do not modify manifests during an audit-only request. Do not infer cluster health
from a clean repository validation.
