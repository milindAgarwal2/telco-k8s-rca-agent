"""MCP tools for bounded read-only Kubernetes observation."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .service import KubernetesService

service = KubernetesService.from_environment()
mcp = MCPServer(
    name="aide-kubernetes-mcp",
    description="Project-scoped read-only Kubernetes observation",
    instructions=(
        "Use only the context and namespace derived from KUBECONFIG or the optional "
        ".aide/local/kubernetes-target.json override. "
        "Never read Secrets, mutate resources, execute in pods, forward ports, "
        "request credentials, or infer health from command success."
    ),
    version="0.1.0",
)


@mcp.tool()
def aide_kubernetes_status() -> dict[str, object]:
    """Report local target and kubectl readiness without cluster access."""
    return service.status()


@mcp.tool()
def aide_verify_kubernetes_context() -> dict[str, object]:
    """Verify pod-read access in the configured context and namespace."""
    return service.verify_context()


@mcp.tool()
def aide_list_kubernetes_workloads(limit: int | None = None) -> dict[str, object]:
    """List projected workload status in the configured namespace."""
    return service.list_workloads(limit)


@mcp.tool()
def aide_list_kubernetes_networking(limit: int | None = None) -> dict[str, object]:
    """List projected Services, EndpointSlices, and Ingresses."""
    return service.list_networking(limit)


@mcp.tool()
def aide_list_kubernetes_events(limit: int = 50) -> dict[str, object]:
    """List bounded recent namespace events with redacted messages."""
    return service.list_events(limit)


@mcp.tool()
def aide_read_kubernetes_resource(kind: str, name: str) -> dict[str, object]:
    """Read one allowlisted resource projection; Secrets are blocked."""
    return service.read_resource(kind, name)


@mcp.tool()
def aide_read_kubernetes_pod_logs(
    pod: str,
    container: str | None = None,
    tail_lines: int | None = None,
    since_seconds: int | None = None,
) -> dict[str, object]:
    """Read bounded current pod logs with credential-like values redacted."""
    return service.pod_logs(pod, container, tail_lines, since_seconds)


def main() -> None:
    """Run the Kubernetes observation server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
