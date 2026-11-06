# Workflow: Monitor Azure resources

## Metadata

- Workflow ID: `aide-monitor-azure-resources`
- Trigger: an explicit Azure inventory, monitoring, or diagnostic request.
- Observer: `aide-azure-observer`
- Skill: `aide-azure-observability`
- Mutation status: prohibited; this workflow ends at observations and findings.

## Inputs and gate

Require a configured project-local Azure target, operator-managed Entra sign-in,
exact subscription and resource group, observation purpose, UTC time window,
named resources when known, and data-redaction boundary. The operator confirms
the scope; the workflow does not perform login or change the active account.

Stop if the target file contains example values, context verification does not
match, access is unavailable, the requested resource is outside the configured
scope, or the only next action is mutating.

## Phase 1: Readiness

Call the Azure MCP status tool and verify the current CLI context. Record CLI
availability, configured scope, subscription and tenant match, and UTC start
time. Do not retain the signed-in user identity or authentication artifacts.

Output: verified observation boundary or `BLOCKED`.

## Phase 2: Inventory

List projected resources in the configured resource group. Record name, type,
kind, location, ARM ID, and tag keys. Select the exact resource IDs relevant to
the request. Do not retrieve unrestricted properties or tag values.

Output: bounded resource inventory and selected observation targets.

## Phase 3: Activity and metrics

Read recent activity for the smallest useful window. For each selected resource,
list available metric definitions, choose named metrics that answer the request,
and query no more than 24 hours using an explicit aggregation and interval.

Output: timestamped, bounded activity and metric observations with truncation.

## Phase 4: Service views

When relevant and configured:

- list Foundry model deployment metadata without endpoints, keys, prompts,
  request content, or data-plane calls;
- list ACR repository and recent tag names without credentials, image pulls,
  layer access, scans, pushes, updates, or deletes.

Output: projected service metadata or a precise unavailable reason.

## Phase 5: Findings and handoff

Separate facts, inferences, hypotheses, contradictions, and unknowns. Report
successful access separately from service health. Provide the smallest next
read-only check. If remediation or new Azure Monitor resources are proposed,
stop and create a separate approval-controlled plan.

Completion requires target and timestamps, verified context, bounded evidence,
explicit gaps, no mutation, and status `OBSERVED`, `NEEDS MORE EVIDENCE`, or
`BLOCKED`.
