# Workflow: Monitor Kubernetes resources

## Metadata

- Workflow ID: `aide-monitor-kubernetes-resources`
- Trigger: explicit Kubernetes inventory, health, or diagnostic request.
- Observer: `aide-kubernetes-observer`
- Skill: `aide-kubernetes-operations`
- Scope: one configured context and namespace; read-only.

## Phase 1: target gate

Require operator-managed `KUBECONFIG`, the exact symptom, time window, and
sensitive-data boundary. Verify the context and namespace derived by the MCP or
the optional ignored target override. Output `BLOCKED` on mismatch or
unavailable access.

## Phase 2: bounded observation

Collect the smallest relevant workload, networking, event, resource-projection,
and redacted log evidence through `@aide-kubernetes-mcp`. Never read Secrets,
exec into pods, forward ports, or mutate resources.

## Phase 3: findings

Separate timestamped facts, hypotheses, relationships, truncation, and gaps.
Successful access is not health proof. Return the smallest next read-only check.
If remediation is proposed, stop and create a separate plan-bound workflow.
