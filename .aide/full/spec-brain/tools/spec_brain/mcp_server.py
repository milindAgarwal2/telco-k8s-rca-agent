"""Read-only MCP surface for exact Neo4j and Graphiti context retrieval."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from typing import Literal

from mcp.server.mcpserver import MCPServer

from tools.spec_brain.config import ConfigurationError, SpecBrainSettings
from tools.spec_brain.context_composer import compose_context
from tools.spec_brain.graphiti_loader import GraphitiRuntime
from tools.spec_brain.retrieval import ExactRetriever

_INSTRUCTIONS = """
Use this server for read-only Graphiti semantic retrieval and combined
Neo4j-plus-Graphiti specification context. Every semantic search is restricted
to the configured Graphiti group. Exact KB_* relationships and current source
or tests remain authoritative. The server exposes no ingestion, episode-add,
update, delete, clear, or schema-management operation.
""".strip()

mcp = MCPServer(
    name="spec-brain-graphiti",
    description="Read-only Neo4j and Graphiti retrieval for Kiro",
    instructions=_INSTRUCTIONS,
    version="0.1.0",
)


def _settings(max_results: int | None = None) -> SpecBrainSettings:
    settings = SpecBrainSettings.from_env()
    if max_results is None:
        return settings
    if not 1 <= max_results <= 50:
        raise ValueError("max_results must be from 1 through 50")
    return replace(settings, max_semantic_results=max_results)


def _request(value: str) -> str:
    request = value.strip()
    if not request:
        raise ValueError("request must not be empty")
    if len(request) > 20_000:
        raise ValueError("request must not exceed 20000 characters")
    return request


def _target_paths(values: list[str] | None) -> tuple[str, ...]:
    paths = tuple(dict.fromkeys(path.strip() for path in values or () if path.strip()))
    if len(paths) > 20:
        raise ValueError("target_paths must contain at most 20 paths")
    return paths


def _configuration_state(
    settings: SpecBrainSettings,
    *,
    query: bool,
) -> tuple[bool, str | None]:
    try:
        if query:
            settings.require_query()
        else:
            settings.require_graphiti()
    except ConfigurationError as exc:
        return False, str(exc)
    return True, None


@mcp.tool()
def spec_brain_graphiti_status() -> dict[str, object]:
    """Report redacted Graphiti configuration and the fixed retrieval boundary."""

    settings = _settings()
    semantic_configured, semantic_error = _configuration_state(
        settings,
        query=False,
    )
    query_configured, query_error = _configuration_state(settings, query=True)
    return {
        "service": "spec-brain-graphiti",
        "status": "ready" if semantic_configured else "configuration-required",
        "read_only": True,
        "mutation_tools_exposed": False,
        "semantic_configured": semantic_configured,
        "query_configured": query_configured,
        "semantic_configuration_error": semantic_error,
        "query_configuration_error": query_error,
        "database": settings.neo4j_graphiti_database,
        "group_id": settings.graphiti_group_id,
        "configuration": settings.redacted_summary(),
    }


@mcp.tool()
async def spec_brain_graphiti_health() -> dict[str, object]:
    """Check Neo4j, model, and embedding services without changing graph data."""

    settings = _settings()
    settings.require_graphiti()
    runtime = GraphitiRuntime.create(settings)
    try:
        await runtime.check_dependencies()
    finally:
        await runtime.close()
    return {
        "service": "spec-brain-graphiti",
        "status": "ready",
        "read_only": True,
        "database": settings.neo4j_graphiti_database,
        "group_id": settings.graphiti_group_id,
    }


@mcp.tool()
async def spec_brain_search_graphiti(
    request: str,
    max_results: int | None = None,
) -> dict[str, object]:
    """Search Graphiti facts within the configured group.

    Args:
        request: Complete engineering question or change request.
        max_results: Optional result limit from 1 through 50.

    Returns:
        Bounded semantic facts with identity, entities, episodes, and time.
    """

    normalized_request = _request(request)
    settings = _settings(max_results)
    settings.require_graphiti()
    runtime = GraphitiRuntime.create(settings)
    try:
        facts = await runtime.search(normalized_request)
    finally:
        await runtime.close()
    return {
        "service": "spec-brain-graphiti",
        "retrieval": "graphiti-core",
        "read_only": True,
        "database": settings.neo4j_graphiti_database,
        "group_id": settings.graphiti_group_id,
        "result_count": len(facts),
        "max_results": settings.max_semantic_results,
        "facts": [asdict(fact) for fact in facts],
    }


@mcp.tool()
async def spec_brain_build_context(
    request: str,
    target_paths: list[str] | None = None,
    mode: Literal["requirements", "design", "tasks", "all"] = "all",
    max_results: int | None = None,
) -> dict[str, object]:
    """Build an authority-ordered exact and semantic context package.

    Args:
        request: Complete engineering question or change request.
        target_paths: Optional repository-relative folders or files.
        mode: Specification phase receiving the context.
        max_results: Optional Graphiti result limit from 1 through 50.

    Returns:
        Graph target metadata and a bounded specification context package.
    """

    normalized_request = _request(request)
    normalized_paths = _target_paths(target_paths)
    settings = _settings(max_results)
    settings.require_query()

    runtime = GraphitiRuntime.create(settings)
    try:
        semantic_facts = await runtime.search(normalized_request)
    finally:
        await runtime.close()

    retriever = ExactRetriever(settings)
    try:
        exact = await asyncio.to_thread(
            retriever.retrieve,
            normalized_request,
            normalized_paths,
            semantic_facts,
        )
    finally:
        retriever.close()

    context = compose_context(
        normalized_request,
        exact,
        semantic_facts,
        mode=mode,
        max_tokens=settings.max_context_tokens or 0,
    )
    return {
        "service": "spec-brain-graphiti",
        "retrieval": "neo4j-exact-plus-graphiti",
        "read_only": True,
        "exact_database": settings.neo4j_kb_database,
        "graphiti_database": settings.neo4j_graphiti_database,
        "group_id": settings.graphiti_group_id,
        "context": context,
    }


def main() -> None:
    """Run the workspace MCP server over standard input and output."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
