# AIDE Azure change MCP

This full-flavor, disabled-by-default server supports one narrow mutation path:
validated Bicep or ARM templates at resource-group scope, Azure What-If, and an
incremental deployment bound to the resulting local plan receipt.

It does not expose arbitrary Azure CLI or REST execution. Complete mode,
deletion, subscription/tenant deployments, RBAC and policy changes, access-token
or key retrieval, and blind retries are outside the tool surface.

## Local configuration

1. Copy `.aide/templates/azure-target.example.json` to the ignored
   `.aide/local/azure-target.json`.
2. Copy `.aide/templates/azure-change-policy.example.json` to the ignored
   `.aide/local/azure-change-policy.json`.
3. Set exact template roots and resource types, then deliberately change
   `enabled` to `true` after review.
4. Complete `az login` outside Kiro and enable the workspace MCP entry.

Prepare and run:

```powershell
uv sync --project .aide/full/mcp-servers/aide-azure-change-mcp --all-groups --frozen
uv run --project .aide/full/mcp-servers/aide-azure-change-mcp `
  --offline --frozen aide-azure-change-mcp
```

Plan receipts contain paths, hashes, projected resource IDs/types/change types,
scope, expiry, and status. They contain no template body, parameters, credential,
Azure token, or raw Azure response and remain under ignored `.aide/local/`.
