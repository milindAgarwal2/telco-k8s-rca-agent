# Monitor project-scoped Azure resources with Kiro

You are working in the current repository. Perform a read-only Azure
observation using the installed AIDE full flavor.

First, inspect `.aide/local/azure-target.json`. If it does not exist, ask the
operator to copy `.aide/templates/azure-target.example.json` there and replace
all example values. Ask for the subscription ID, optional tenant ID, resource
group, optional Foundry account, optional Azure Container Registry, observation
purpose, time window, and redaction boundary. Never ask for a token, key,
password, client secret, or Azure CLI cache file.

The operator performs `az login` and subscription selection outside this
workflow. Do not run login, logout, `account set`, `account get-access-token`,
key, credential, role-assignment, deployment mutation, or resource mutation.

Use the `aide-azure-observer`, `aide-azure-observability` skill,
`aide-monitor-azure-resources` workflow, and `@aide-azure-mcp` tools:

1. Check server readiness and verify subscription/tenant context.
2. Inventory the configured resource group.
3. Read bounded recent activity.
4. List metric definitions before querying only relevant metrics.
5. If configured and relevant, list Foundry deployment metadata and ACR
   repository/tag names.
6. Separate timestamped facts from hypotheses and state all gaps/truncation.
7. Stop before remediation and return the smallest next read-only check.

Return `OBSERVED`, `NEEDS MORE EVIDENCE`, or `BLOCKED`. A successful command
proves access to that observation only; do not claim overall service health.
