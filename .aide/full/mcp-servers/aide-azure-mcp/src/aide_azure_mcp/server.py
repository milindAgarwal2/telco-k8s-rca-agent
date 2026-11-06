"""MCP tools for bounded read-only Azure resource observation."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .service import AzureService

_INSTRUCTIONS = """
Use this server only for read-only observation of the Azure target declared in
.aide/local/azure-target.json. Authentication comes from the operator's
existing Azure CLI Microsoft Entra session. Never request or expose tokens,
keys, credentials, endpoints, claims, or unrestricted resource properties.
Do not infer health from a successful command; report timestamps, scope,
observations, gaps, and failures. The server has no mutation or login tools.
""".strip()

service = AzureService.from_environment()
mcp = MCPServer(
    name="aide-azure-mcp",
    description="Project-scoped read-only Azure CLI observability",
    instructions=_INSTRUCTIONS,
    version="0.1.0",
)


@mcp.tool()
def aide_azure_status() -> dict[str, object]:
    """Report local Azure target and CLI readiness without remote mutation."""
    return service.status()


@mcp.tool()
def aide_verify_azure_context() -> dict[str, object]:
    """Verify the signed-in tenant and subscription against project scope."""
    return service.verify_context()


@mcp.tool()
def aide_list_resource_group_resources(limit: int = 100) -> dict[str, object]:
    """List projected resources from the configured resource group."""
    return service.list_resources(limit)


@mcp.tool()
def aide_list_recent_azure_activity(
    hours: int | None = None, max_events: int | None = None
) -> dict[str, object]:
    """List bounded recent activity without callers, claims, or properties."""
    return service.list_activity(hours, max_events)


@mcp.tool()
def aide_list_azure_metric_definitions(
    resource_id: str, limit: int = 100
) -> dict[str, object]:
    """List metric definitions for one configured-scope resource."""
    return service.metric_definitions(resource_id, limit)


@mcp.tool()
def aide_query_azure_metrics(
    resource_id: str,
    metric_names: list[str],
    hours: int | None = None,
    interval: str | None = None,
    aggregation: str = "Average",
) -> dict[str, object]:
    """Query selected metrics for at most 24 hours with bounded points."""
    return service.query_metrics(
        resource_id, metric_names, hours, interval, aggregation
    )


@mcp.tool()
def aide_list_foundry_deployments(limit: int = 100) -> dict[str, object]:
    """List safe model deployment metadata for the configured Foundry resource."""
    return service.foundry_deployments(limit)


@mcp.tool()
def aide_list_acr_repositories(limit: int = 100) -> dict[str, object]:
    """List repository names from the configured container registry."""
    return service.acr_repositories(limit)


@mcp.tool()
def aide_list_acr_tags(repository: str, limit: int = 30) -> dict[str, object]:
    """List recent tag names for a repository in the configured registry."""
    return service.acr_tags(repository, limit)


def main() -> None:
    """Run the Azure observability server over standard input/output."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
