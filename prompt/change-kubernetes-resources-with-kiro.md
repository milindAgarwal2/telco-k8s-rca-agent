# Change project-scoped Kubernetes resources with Kiro

Use `aide-kubernetes-operator`, `aide-kubernetes-change-control`,
`aide-deploy-kubernetes-resources`, and `@aide-kubernetes-change-mcp`.

1. Require a reviewed effective target derived from `KUBECONFIG` or its optional
   local override, an explicitly enabled `.aide/local/kubernetes-change-policy.json`,
   a reviewed repository manifest, health checks, abort criteria, and recovery plan.
2. Check status and validate the exact manifest.
3. Run server-side dry-run and present plan ID, expiry, hash, target, and every
   object/operation.
4. Stop for approvals bound to `kubernetes-plan:<plan-id>`; do not self-approve.
5. Apply once using exact `APPLY <plan-id>` confirmation.
6. Verify through `@aide-kubernetes-mcp`. Never retry an uncertain result.

No direct kubectl, delete, patch, scale, exec, port-forward, prune, Helm,
force-conflicts, cluster-scoped changes, credential handling, or policy edits.
