# AIDE Kubernetes observation MCP

This project-local MCP exposes fixed, read-only `kubectl` operations for one
context and namespace. By default it derives and fingerprints the active target
from the operator's `KUBECONFIG`; an ignored
`.aide/local/kubernetes-target.json` is an optional explicit override. It never
logs in, reads Secret values, or exposes arbitrary commands.

Prepare it with `uv sync --offline --frozen`. Live cluster access remains
unavailable until operator-managed `KUBECONFIG` is present and valid.
