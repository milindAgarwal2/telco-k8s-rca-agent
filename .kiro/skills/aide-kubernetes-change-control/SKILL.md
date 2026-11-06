---
name: aide-kubernetes-change-control
description: Validate, server-side dry-run plan, approve, and apply one hash-bound namespaced Kubernetes manifest through the disabled-by-default AIDE Kubernetes change MCP.
---
# AIDE Kubernetes change control

Use only for an explicit request to create or update namespaced resources from a
reviewed repository manifest. Observation belongs to `aide-kubernetes-operations`.

Require the full flavor, reviewed effective target, enabled local change policy,
operator-managed `KUBECONFIG`, approved specification, manifest, expected
health, abort criteria, and recovery plan. Never request credentials. The
installed policy template is deliberately disabled and is not authorization.

1. Call `aide_kubernetes_change_status`; stop on every problem.
2. Validate the exact manifest path and hash.
3. Call `aide_plan_kubernetes_apply`; review every object, operation, expiry, and target.
4. Initialize workflow approval for `kubernetes-plan:<plan-id>` and obtain explicit
   specification and operations approvals. Kiro permission prompting is additional.
5. Apply only the same unexpired plan with `APPLY <plan-id>`.
6. Verify health through the observer MCP. Do not infer recovery from apply output.
7. On any interruption or error, report `OUTCOME_UNKNOWN` and do not retry.

No direct kubectl, delete, patch, scale, exec, port-forward, prune, force
conflicts, Helm, cluster-scoped kinds, policy broadening, or automatic repair.
