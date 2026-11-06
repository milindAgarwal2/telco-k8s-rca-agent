"""MCP tools for plan-bound Kubernetes server-side apply."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .service import KubernetesChangeService

service = KubernetesChangeService.from_environment()
mcp = MCPServer(
    name="aide-kubernetes-change-mcp",
    description="Plan-bound namespaced Kubernetes create/update",
    instructions=(
        "Use only reviewed repository manifests. Validate, run server-side dry-run, "
        "present the plan, and stop for approvals bound to kubernetes-plan:<plan-id>. "
        "Apply once with exact confirmation. Never delete, patch, scale, exec, prune, "
        "force conflicts, run arbitrary kubectl, or retry an uncertain outcome."
    ),
    version="0.1.0",
)


@mcp.tool()
def aide_kubernetes_change_status() -> dict[str, object]:
    """Report local target, policy, plan-store, and kubectl readiness."""
    return service.status()


@mcp.tool()
def aide_validate_kubernetes_manifest(manifest_path: str) -> dict[str, object]:
    """Validate one local manifest path and return its hash."""
    return service.validate_manifest(manifest_path)


@mcp.tool()
def aide_plan_kubernetes_apply(manifest_path: str) -> dict[str, object]:
    """Run server-side dry-run and persist an expiring plan receipt."""
    return service.plan_manifest(manifest_path)


@mcp.tool()
def aide_apply_kubernetes_manifest(
    plan_id: str, confirmation: str
) -> dict[str, object]:
    """Apply one approved, unchanged, unexpired manifest plan."""
    return service.apply_manifest(plan_id, confirmation)


@mcp.tool()
def aide_get_kubernetes_change_status(plan_id: str) -> dict[str, object]:
    """Read the local status of one Kubernetes plan receipt."""
    return service.plan_status(plan_id)


def main() -> None:
    """Run the Kubernetes change server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
