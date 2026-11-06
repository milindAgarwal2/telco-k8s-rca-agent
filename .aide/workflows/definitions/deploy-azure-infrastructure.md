# Workflow: Deploy Azure infrastructure

## Metadata

- Workflow ID: `aide-deploy-azure-infrastructure`
- Trigger: explicit request to create or update Azure resources from reviewed IaC.
- Operator: `aide-azure-operator`
- Skill: `aide-azure-change-control`
- Scope: one configured resource group; Incremental deployment only.

## Phase 1: specification and IaC review

Review requirements, design, tasks, Bicep/ARM template, parameter file, target,
resource-type allowlist, maximum changes, checks, rollback/recovery notes, and
current worktree. IaC authoring and tests use the normal approved-change loop;
cloud deployment is not part of its automatic repair cycle.

Output: reviewed immutable deployment inputs or `BLOCKED`.

## Phase 2: local validation and What-If

Check change-server status, validate files, and run one resource-group What-If.
Record hashes, plan ID, expiry, deployment name, and every projected resource
ID/type/change. Delete, Ignore, Deploy, unsupported, out-of-scope, or excessive
changes stop the workflow.

Output: `PLANNED` receipt or `BLOCKED`.

## Gate A: specification approval

Initialize AIDE workflow state for the reviewed spec and target
`azure-plan:<plan-id>`. Obtain explicit spec-readiness approval. Changed inputs
or an expired plan return to Phase 2.

## Gate B: operations approval

Obtain explicit operations approval bound to task, revision, scope hash, and
`azure-plan:<plan-id>`. Kiro permission prompting does not replace this gate.

## Phase 3: apply once

Revalidate receipt, target, policy, file hashes, expiry, and Entra context. Call
apply with `APPLY <plan-id>`. The MCP uses only `az deployment group create`
with Incremental mode. No automatic retry is allowed.

Output: `APPLIED`, `FAILED`, or `OUTCOME_UNKNOWN`.

## Phase 4: evidence and handoff

Read deployment status and capture only bounded plan/deployment metadata. Do not
retain template parameters, credentials, or raw responses. For
`OUTCOME_UNKNOWN`, a human inspects Azure deployment operations before deciding
whether a new plan is safe. Complete only after reviewable evidence and an
explicit final status.
