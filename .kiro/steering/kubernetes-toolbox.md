---
inclusion: always
---
# Kubernetes access policy

Keep kubeconfig and credentials outside the repository; authentication belongs
to the human operator. The full installation derives and fingerprints the
active context and namespace from `KUBECONFIG`. An ignored project-local target
descriptor is an optional override. Use `aide-kubernetes-mcp` for bounded
read-only observation of that effective target. Never read Secrets, exec,
attach, proxy, or forward ports.

Live creation or update requires the separate disabled-by-default
`aide-kubernetes-change-mcp`, reviewed repository manifests, an enabled local
allowlist policy, server-side dry-run, an unexpired hash-bound plan, exact
confirmation, and approvals bound to `kubernetes-plan:<plan-id>`. Only
namespaced server-side apply without force conflicts is supported. Deletion,
patch, scale, prune, Helm, cluster-scoped changes, arbitrary commands, and
automatic retry are prohibited. Treat uncertain outcomes as requiring human
inspection.
