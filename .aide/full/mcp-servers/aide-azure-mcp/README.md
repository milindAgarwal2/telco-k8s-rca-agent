# AIDE Azure observability MCP

This project-local MCP server exposes a small, read-only Azure observability
surface through the installed Azure CLI. It reuses the operator's existing
Microsoft Entra sign-in and never retrieves, prints, copies, or stores access
tokens.

Copy `.aide/templates/azure-target.example.json` to the ignored
`.aide/local/azure-target.json` file and replace every example value. The
server pins every request to that subscription and resource group. Foundry and
Azure Container Registry tools are available only when their resource names
are configured.

The service runs Azure CLI with `shell=False`, fixed command families, JSON
output, bounded time windows, and bounded result counts. It has no create,
update, deployment, role-assignment, key, credential, login, or token tool.

Start it as Kiro does:

```powershell
uv run --project .aide/full/mcp-servers/aide-azure-mcp `
  --offline --frozen aide-azure-mcp
```

An absent Azure CLI, expired sign-in, missing target file, or target mismatch
is reported as blocked. The operator performs `az login` and any account
selection outside the agent workflow.
