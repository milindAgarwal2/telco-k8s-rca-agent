---
name: aide-azure-change-control
description: Validate, What-If plan, approve, and apply one hash-bound incremental Azure resource-group Bicep or ARM deployment through the disabled-by-default AIDE Azure change MCP.
---

# AIDE Azure change control

Use only for an explicit request to create or update Azure resources from a
reviewed repository Bicep or ARM template. Observation remains with
`aide-azure-observability` and `@aide-azure-mcp`.

## Preconditions

Require the full flavor, reviewed `.aide/local/azure-target.json`, an explicitly
enabled `.aide/local/azure-change-policy.json`, operator-owned `az login`, the
disabled-by-default server deliberately enabled, reviewed specification and IaC
files, and Azure RBAC for What-If and deployment. Never request credentials.

## Procedure

1. Call `aide_azure_change_status` and stop on every problem.
2. Validate workspace-relative template and parameter files. Record hashes.
3. Call `aide_plan_azure_deployment`. Review every resource ID, resource type,
   change type, plan ID, expiry, and the fixed Incremental mode.
4. Scope-check and omit Incremental Ignore entries. Reject Delete, Deploy,
   unknown, excessive, unlisted-type, or
   out-of-resource-group results. The server also enforces these checks.
5. Initialize the existing AIDE workflow for the exact plan ID. Obtain spec
   readiness and then operations approval with target `azure-plan:<plan-id>`.
6. Call apply only with the unchanged, unexpired plan and exact confirmation
   `APPLY <plan-id>`.
7. Read deployment status, record redacted evidence, and stop. If dispatch or
   outcome is uncertain, return OUTCOME_UNKNOWN and require human recovery.

## Boundaries

- No arbitrary Azure CLI/REST, Complete mode, deletes, RBAC, policy, locks,
  subscription/tenant deployment, token/key operations, or automatic retry.
- Do not edit the template, parameters, target, policy, scope, or approval after
  What-If. Any change requires a new plan and approval.
- The server and hooks add defense in depth; Azure RBAC, Policy, locks, and
  organizational review remain authoritative.

## Output

Return target, template/parameter hashes, plan ID and expiry, projected changes,
approvals, deployment status, correlation ID when available, evidence location,
gaps, and PLANNED, BLOCKED, APPLIED, FAILED, or OUTCOME_UNKNOWN.
