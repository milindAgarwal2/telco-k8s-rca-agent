"""MCP tool surface for prioritized repository knowledge retrieval."""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer

from .config import Settings
from .index import KnowledgeIndex

_INSTRUCTIONS = """
Use this server for repository architecture and specification context.
Read knowledge-base results first. Use OpenWiki results only as secondary
explanation and navigation. Neither documentation tier overrides source code,
schemas, or tests. Preserve citations and uncertainty labels. Do not infer
behavior that the returned evidence does not establish. All tools are
read-only with respect to repository files.
""".strip()

settings = Settings.from_environment()
index = KnowledgeIndex(settings)
mcp = MCPServer(
    name="aide-knowledge-mcp",
    description=(
        "Read-only prioritized retrieval over knowledge-base and OpenWiki Markdown"
    ),
    instructions=_INSTRUCTIONS,
    version="0.1.0",
)


@mcp.tool()
def aide_knowledge_status() -> dict[str, object]:
    """Report source availability, index counts, limits, and warnings."""
    return index.status()


@mcp.tool()
def aide_search_knowledge(
    query: str,
    limit: int = 12,
    include_secondary: bool = True,
) -> dict[str, object]:
    """Search primary knowledge and optional secondary OpenWiki evidence.

    Args:
        query: Complete engineering question or specification topic.
        limit: Maximum combined results, from 1 through 50.
        include_secondary: Whether OpenWiki may fill the secondary result share.

    Returns:
        Structured, citation-bearing primary and secondary result lists.
    """
    return index.search(query, limit, include_secondary)


@mcp.tool()
def aide_build_knowledge_context(
    request: str,
    target_paths: list[str] | None = None,
    limit: int = 12,
    max_chars: int | None = None,
) -> dict[str, object]:
    """Build bounded context for Kiro requirements, design, or task specs.

    Args:
        request: The complete user request without semantic rewriting.
        target_paths: Optional repository paths that sharpen retrieval.
        limit: Maximum combined evidence results, from 1 through 50.
        max_chars: Optional Markdown context ceiling within the configured limit.

    Returns:
        Ordered primary and secondary evidence plus bounded Markdown context.
    """
    return index.build_context(request, target_paths, limit, max_chars)


@mcp.tool()
def aide_read_knowledge_document(
    relative_path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict[str, object]:
    """Read a bounded range from an indexed knowledge Markdown file.

    Args:
        relative_path: Repository-relative path under knowledge-base or OpenWiki.
        start_line: One-based first line.
        end_line: Optional inclusive last line.

    Returns:
        Redacted content with exact line citation and source tier.
    """
    return index.read_document(relative_path, start_line, end_line)


@mcp.tool()
def aide_list_knowledge_documents(
    source: Literal["all", "primary", "secondary"] = "all",
    prefix: str = "",
    limit: int = 200,
) -> dict[str, object]:
    """List indexed Markdown documents without reading their bodies.

    Args:
        source: all, primary, or secondary.
        prefix: Optional repository-relative path prefix.
        limit: Maximum documents, from 1 through 500.

    Returns:
        Document metadata and source classification.
    """
    return index.list_documents(source, prefix, limit)


@mcp.tool()
def aide_refresh_knowledge_index() -> dict[str, object]:
    """Rebuild only the in-memory index, without changing source files."""
    changed = index.refresh(force=True)
    result = index.status()
    result["rebuilt"] = changed
    return result


def main() -> None:
    """Run the local MCP server over standard input and output."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
