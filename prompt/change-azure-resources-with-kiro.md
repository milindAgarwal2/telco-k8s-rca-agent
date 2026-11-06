# Change project-scoped Azure resources with Kiro

Use the `aide-azure-operator`, `aide-azure-change-control` skill,
`aide-deploy-azure-infrastructure` workflow, and
`@aide-azure-change-mcp`. The current observer MCP remains read-only.

Ask for the reviewed repository-relative Bicep or ARM template and optional JSON
parameter file, task ID, plan revision, specification directory, and deployment
purpose. Do not ask for credentials. Require the operator to complete `az login`
outside Kiro and to configure the ignored target and change-policy files.

1. Check status and validate the local inputs.
2. Run What-If only. Present hashes, scope, plan ID, expiry, and every projected
   resource ID, type, and change.
3. Stop on any blocked change or policy mismatch.
4. Stop for spec-readiness and operations approval bound to
   `azure-plan:<plan-id>`. Do not self-approve.
5. After both gates, call apply once with exact confirmation `APPLY <plan-id>`.
6. Read deployment status and return bounded evidence.

Never run direct Azure CLI/REST, Complete mode, delete, RBAC/policy changes,
subscription/tenant deployment, credential operations, or automatic retry.
If apply is interrupted or fails ambiguously, return `OUTCOME_UNKNOWN` and stop.
