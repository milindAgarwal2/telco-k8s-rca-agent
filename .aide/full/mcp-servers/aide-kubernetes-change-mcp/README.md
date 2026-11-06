# AIDE Kubernetes change MCP

This disabled-by-default server validates an approved manifest path, performs
server-side dry-run, stores an expiring hash-bound plan, and applies that exact
manifest once after an exact confirmation and AIDE operations approval.
It derives and fingerprints the active target from `KUBECONFIG` unless an
ignored target override exists. The full installation supplies a disabled
policy template; an enabled ignored local allowlist policy is still required
before planning or applying a change.
It supports namespaced create/update only. It has no delete, patch, scale,
exec, port-forward, arbitrary command, force-conflict, prune, Helm, or
cluster-scoped mutation tool.
