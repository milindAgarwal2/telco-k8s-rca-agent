"""MCP tool surface for architecture and design evidence."""

from __future__ import annotations

from aide_knowledge_mcp.index import KnowledgeIndex
from mcp.server.mcpserver import MCPServer

from .config import ArchitectureSettings
from .service import ArchitectureService

_INSTRUCTIONS = """
Use this server when reasoning about architecture, High-Level Design (HLD),
Low-Level Design (LLD), component boundaries, interfaces, flows, ownership, or
change impact. Treat knowledge-base evidence as primary and OpenWiki evidence
as secondary. Source code, schemas, and tests remain authoritative. Preserve
citations, keep unresolved questions visible, and never convert a static
dependency declaration into an invented runtime call. All tools are read-only.
""".strip()

settings = ArchitectureSettings.from_environment()
service = ArchitectureService(KnowledgeIndex(settings.knowledge))
mcp = MCPServer(
    name="aide-architecture-mcp",
    description="Read-only HLD, LLD, relationship, and OpenWiki evidence",
    instructions=_INSTRUCTIONS,
    version="0.1.0",
)


@mcp.tool()
def aide_architecture_status() -> dict[str, object]:
    """Report architecture source health, views, counts, and limits."""
    return service.status()


@mcp.tool()
def aide_search_architecture(
    query: str,
    level: str = "both",
    target_paths: list[str] | None = None,
    limit: int = 12,
) -> dict[str, object]:
    """Search architecture evidence and classify it by architectural view.

    Args:
        query: Complete architecture or design question.
        level: hld, lld, or both.
        target_paths: Optional repository paths that sharpen retrieval.
        limit: Maximum combined evidence results, from 1 through 50.

    Returns:
        Primary and secondary evidence grouped into architecture views.
    """
    return service.search(query, level, target_paths, limit)


@mcp.tool()
def aide_build_architecture_context(
    request: str,
    level: str = "both",
    target_paths: list[str] | None = None,
    limit: int = 16,
    max_chars: int | None = None,
) -> dict[str, object]:
    """Build bounded, citation-bearing context for HLD or LLD work.

    Args:
        request: Complete design or change request.
        level: hld, lld, or both.
        target_paths: Optional affected repository paths.
        limit: Maximum combined evidence results, from 1 through 50.
        max_chars: Optional context ceiling within the configured maximum.

    Returns:
        Ordered evidence, architecture views, gaps, and review checklist.
    """
    return service.build_context(
        request,
        level,
        target_paths,
        limit,
        max_chars,
    )


@mcp.tool()
def aide_trace_architecture_relationships(
    component_or_path: str,
    limit: int = 20,
) -> dict[str, object]:
    """Find declared dependency and interaction evidence for a subject.

    Args:
        component_or_path: Component name or repository-relative path.
        limit: Maximum combined evidence results, from 1 through 50.

    Returns:
        Relationship-map, design, and secondary OpenWiki evidence.
    """
    return service.trace_relationships(component_or_path, limit)


@mcp.tool()
def aide_read_architecture_evidence(
    relative_path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict[str, object]:
    """Read an exact bounded range from architecture knowledge.

    Args:
        relative_path: Markdown path under knowledge-base or OpenWiki.
        start_line: One-based first line.
        end_line: Optional inclusive last line.

    Returns:
        Redacted content with source tier and exact line citation.
    """
    return service.read_evidence(relative_path, start_line, end_line)


@mcp.tool()
def aide_refresh_architecture_index() -> dict[str, object]:
    """Refresh only the in-memory architecture index."""
    return service.refresh()


def main() -> None:
    """Run the local architecture MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
