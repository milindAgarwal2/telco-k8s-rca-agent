---
name: aide-azure-observability
description: Observe one project-scoped Azure subscription and resource group through the bounded AIDE Azure MCP, including resource inventory, activity, metrics, Foundry deployments, and ACR repositories, without changing cloud state or exposing credentials.
---

# AIDE Azure observability

Use this skill when the user asks to inspect, monitor, inventory, or diagnose an
Azure resource group, Azure AI Foundry account, Azure Monitor signal, or Azure
Container Registry through an existing Azure CLI Microsoft Entra session.

## Preconditions

1. Require a full AIDE installation and the `aide-azure-mcp` workspace server.
2. Require the operator to complete `az login` outside the agent workflow.
3. Copy `.aide/templates/azure-target.example.json` to the ignored
   `.aide/local/azure-target.json` path and replace every example value.
4. Confirm the subscription ID, optional tenant ID, resource group, Foundry
   account, registry, time window, and sensitive-data boundary with the user.
5. Never request an access token, API key, password, client secret, refresh
   token, or a copy of the Azure CLI cache.

## Observation procedure

1. Call `aide_azure_status`. Stop if configuration or Azure CLI is blocked.
2. Call `aide_verify_azure_context`. Stop on tenant or subscription mismatch.
3. List resource-group resources and establish exact ARM resource IDs.
4. Read recent activity for the smallest useful window, normally one hour.
5. For a named resource, list metric definitions before querying selected
   metrics. Query at most 24 hours and state aggregation and interval.
6. For Foundry, list deployment metadata. Do not retrieve endpoints, keys,
   prompts, inference payloads, content, quotas outside the configured account,
   or user identity.
7. For ACR, list repository and tag names only. Do not authenticate Docker,
   retrieve credentials, pull images, scan layers, push, tag, untag, or delete.
8. Record target, UTC collection time, command/tool, returned scope, gaps, and
   whether the signal is a fact, inference, or hypothesis.

## Boundaries

- Use only `@aide-azure-mcp` for cloud observations. Do not run direct Azure
  CLI resource commands from a shell.
- The operator owns interactive login and subscription selection.
- Do not create alerts, diagnostics, deployments, role assignments, locks,
  budgets, dashboards, resources, or configuration.
- Do not call `az account get-access-token`, list keys or credentials, use
  `az rest`, or retain raw Azure response bodies in the repository.
- A successful query proves access to that observation only. It does not prove
  service health, absence of incidents, correct configuration, or data-plane
  connectivity.

## Output contract

Return the configured target and UTC observation time; access/context result;
resource inventory; relevant activity, metric, Foundry, and ACR observations;
facts separated from hypotheses; unavailable signals and truncation; the
smallest next read-only check; and status as `OBSERVED`,
`NEEDS MORE EVIDENCE`, or `BLOCKED`. Any remediation remains a separate,
explicitly authorized workflow.
