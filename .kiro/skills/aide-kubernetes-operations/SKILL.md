---
name: aide-kubernetes-operations
description: Observe and diagnose one explicitly configured Kubernetes context and namespace through the bounded read-only AIDE Kubernetes MCP without reading Secrets or changing cluster state.
---
# AIDE Kubernetes observation

Use for current workload, networking, event, condition, or log evidence. Require
the full flavor, operator-managed `KUBECONFIG`, the effective context/namespace,
symptom, time window, and data boundary. The runtime derives the target from the
kubeconfig unless an ignored `.aide/local/kubernetes-target.json` override is
present.

1. Call `aide_kubernetes_status`, then `aide_verify_kubernetes_context`.
2. Stop on missing configuration, access failure, context mismatch, or ambiguity.
3. List the smallest relevant workload and networking set.
4. Read only allowlisted projected resources. Secret reads are prohibited.
5. Use bounded current pod logs only when needed; report redaction/truncation.
6. Separate timestamped observations, relationships, hypotheses, and unknowns.
7. Hand any mutation to `aide-kubernetes-change-control` and its separate MCP.

Use only `@aide-kubernetes-mcp` for cluster observation. Do not run direct
cluster-reading shell commands, exec, attach, port-forward, proxy, credential
commands, or mutation. A successful command proves access only.
