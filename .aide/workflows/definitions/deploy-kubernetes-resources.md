# Workflow: Deploy Kubernetes resources

## Metadata

- Workflow ID: `aide-deploy-kubernetes-resources`
- Trigger: explicit request to create or update namespaced resources from reviewed manifests.
- Operator: `aide-kubernetes-operator`
- Skill: `aide-kubernetes-change-control`
- Scope: one configured context and namespace; server-side apply only.

## Phase 1: specification and manifest review

Review requirements, design, tasks, manifest, target, kind allowlist, health
checks, abort criteria, recovery notes, and worktree. Output reviewed immutable
inputs or `BLOCKED`.

## Phase 2: server-side dry-run

Check change-server status, validate the manifest, and plan once. Record plan ID,
expiry, hashes, and every projected object/operation. Unsupported kinds, wrong
namespace, excessive objects, or policy violations stop the workflow.

## Gates

Bind specification and operations approval to `kubernetes-plan:<plan-id>`.
Changed inputs, dry-run results, target/policy, or expiry require a new plan.

## Phase 3: apply once and verify

Call apply with `APPLY <plan-id>`. No automatic retry is allowed. Verify health
through the observer MCP. Failure or interruption is `OUTCOME_UNKNOWN` until a
human inspects current cluster state and decides the next action.
