"""MCP tools for plan-bound Azure resource-group deployments."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .service import AzureChangeService

_INSTRUCTIONS = """
Use this server only for explicitly reviewed resource-group Bicep or ARM
deployments. Start with local status and validation, run What-If, present the
exact plan ID and projected changes, and stop for human specification and
operations approval. Apply only that unexpired plan with the exact confirmation
string. Never request credentials, run arbitrary Azure CLI or REST commands,
use complete mode, delete resources, change RBAC or policy, retry an uncertain
outcome, or expand beyond the configured subscription and resource group.
""".strip()

service = AzureChangeService.from_environment()
mcp = MCPServer(
    name="aide-azure-change-mcp",
    description="Plan-bound incremental Azure resource-group deployments",
    instructions=_INSTRUCTIONS,
    version="0.1.0",
)


@mcp.tool()
def aide_azure_change_status() -> dict[str, object]:
    """Report local target, policy, plan-store, and Azure CLI readiness."""
    return service.status()


@mcp.tool()
def aide_validate_azure_deployment(
    template_path: str, parameters_path: str | None = None
) -> dict[str, object]:
    """Validate local deployment inputs and return content hashes."""
    return service.validate_deployment(template_path, parameters_path)


@mcp.tool()
def aide_plan_azure_deployment(
    template_path: str,
    parameters_path: str | None = None,
    deployment_name: str | None = None,
) -> dict[str, object]:
    """Run bounded Azure What-If and persist an expiring plan receipt."""
    return service.plan_deployment(template_path, parameters_path, deployment_name)


@mcp.tool()
def aide_apply_azure_deployment(
    plan_id: str, confirmation: str
) -> dict[str, object]:
    """Apply one approved, unchanged, unexpired incremental plan."""
    return service.apply_deployment(plan_id, confirmation)


@mcp.tool()
def aide_get_azure_deployment_status(plan_id: str) -> dict[str, object]:
    """Read local and Azure deployment status for one plan receipt."""
    return service.deployment_status(plan_id)


def main() -> None:
    """Run the Azure change server over standard input/output."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
