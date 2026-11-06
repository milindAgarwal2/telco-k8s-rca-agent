# Monitor project-scoped Kubernetes resources with Kiro

Use `aide-kubernetes-observer`, the `aide-kubernetes-operations` skill,
`aide-monitor-kubernetes-resources` workflow, and `@aide-kubernetes-mcp`.

Require only operator-managed `KUBECONFIG`. The MCP derives and fingerprints its
active context and namespace. If `.aide/local/kubernetes-target.json` exists,
treat it as an explicit override and verify it. Never ask for tokens, client
certificates, passwords, or kubeconfig contents.

Call status and verify context. Then collect only the workloads, networking,
events, projected resource metadata, or bounded redacted logs needed for the
request. Never read Secrets, run arbitrary kubectl, exec, attach, port-forward,
proxy, or mutate. Report timestamps, facts, hypotheses, gaps, truncation, and
`OBSERVED`, `NEEDS MORE EVIDENCE`, or `BLOCKED`.
