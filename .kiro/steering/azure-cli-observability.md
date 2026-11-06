---
inclusion: always
---
# Azure CLI access policy

For Azure access, use ignored project-local target and policy descriptors;
never commit tenant-specific credentials or Azure CLI cache content.
Interactive Microsoft Entra sign-in and subscription selection belong to the
human operator. Agents must not invoke login, logout, account mutation,
access-token, key, credential, arbitrary REST, or direct resource-change
commands.

Use `aide-azure-mcp` for bounded observation. It is always read-only and limits
every query to the configured subscription and resource group.

Azure resource creation or update requires the separate disabled-by-default
`aide-azure-change-mcp`, reviewed Bicep/ARM inputs, an explicitly enabled local
allowlist policy, What-If, an unexpired hash-bound plan, exact confirmation, and
operations approval bound to `azure-plan:<plan-id>`. Only Incremental
resource-group deployment is supported. Never use Complete mode, deletion,
RBAC/policy changes, broader scopes, arbitrary commands, or automatic retry.

On any uncertain mutation outcome, stop and inspect deployment status. Do not
infer rollback or retry safety.
