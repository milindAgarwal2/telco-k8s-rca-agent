"""MCP tool surface for evidence-backed Kiro specification work."""

from __future__ import annotations

from aide_architecture_mcp.service import ArchitectureService
from aide_knowledge_mcp.index import KnowledgeIndex
from mcp.server.mcpserver import MCPServer

from .config import SpecSettings
from .service import SpecificationService

_INSTRUCTIONS = """
Use this server when preparing or reviewing Kiro requirements.md, design.md,
or tasks.md. The user request or selected Jira-style story defines desired
behavior; source, schemas, configuration, and tests establish current behavior.
Use knowledge-base as primary architecture context and OpenWiki as secondary
discovery context. Verify normative implementation claims in repository source
and focused tests. Preserve citations, label evidence and inference, expose
unknowns, and treat generated specifications as drafts pending maintainer or
subject-matter expert review. All tools are local and read-only.
""".strip()

settings = SpecSettings.from_environment()
index = KnowledgeIndex(settings.architecture.knowledge)
architecture = ArchitectureService(index)
service = SpecificationService(settings, architecture)
mcp = MCPServer(
    name="aide-spec-mcp",
    description=(
        "Read-only Jira, requirements, design, task, and traceability evidence"
    ),
    instructions=_INSTRUCTIONS,
    version="0.1.0",
)


@mcp.tool()
def aide_spec_status() -> dict[str, object]:
    """Report sources, supported artifacts, safety boundaries, and limits."""
    return service.status()


@mcp.tool()
def aide_list_spec_stories(limit: int = 100) -> dict[str, object]:
    """List available Jira-style Markdown requirement inputs.

    Args:
        limit: Maximum documents to return, from 1 through 200.

    Returns:
        Story paths and sizes without document bodies.
    """
    return service.list_stories(limit)


@mcp.tool()
def aide_search_spec_evidence(
    query: str,
    artifact: str = "all",
    target_paths: list[str] | None = None,
    limit: int = 16,
) -> dict[str, object]:
    """Search architecture evidence for a specification artifact.

    Args:
        query: Complete requirement, design, task, or review question.
        artifact: requirements, design, tasks, or all.
        target_paths: Optional affected repository paths.
        limit: Maximum combined evidence results, from 1 through 50.

    Returns:
        Primary and secondary evidence with artifact-specific guidance.
    """
    return service.search(query, artifact, target_paths, limit)


@mcp.tool()
def aide_resolve_folder_specifications(
    target_paths: list[str],
) -> dict[str, object]:
    """Find existing ancestor folder contracts for affected paths.

    Args:
        target_paths: One through 20 repository-relative files or folders.

    Returns:
        Existing ancestor SPECS.md paths and their evidence rule.
    """
    return service.resolve_folder_specs(target_paths)


@mcp.tool()
def aide_build_spec_context(
    request: str,
    artifact: str = "all",
    story_path: str | None = None,
    target_paths: list[str] | None = None,
    limit: int = 18,
    max_chars: int | None = None,
) -> dict[str, object]:
    """Build a bounded evidence packet for Kiro specification generation.

    Args:
        request: Complete requested change or specification objective.
        artifact: requirements, design, tasks, or all.
        story_path: Optional Jira-style Markdown path under the configured folder.
        target_paths: Optional affected repository paths.
        limit: Maximum combined knowledge results, from 1 through 50.
        max_chars: Optional rendered-context ceiling within the configured limit.

    Returns:
        Story, folder-contract, architecture, EARS, and traceability context.
    """
    return service.build_context(
        request,
        artifact,
        story_path,
        target_paths,
        limit,
        max_chars,
    )


@mcp.tool()
def aide_build_spec_traceability(
    request: str,
    story_path: str | None = None,
    target_paths: list[str] | None = None,
    limit: int = 16,
) -> dict[str, object]:
    """Prepare evidence anchors and required traceability mappings.

    Args:
        request: Complete requested change or specification objective.
        story_path: Optional Jira-style Markdown requirement source.
        target_paths: Optional affected repository paths.
        limit: Maximum combined knowledge results, from 1 through 50.

    Returns:
        Evidence citations, mapping rules, and traceability matrix columns.
    """
    return service.traceability_plan(
        request,
        story_path,
        target_paths,
        limit,
    )


@mcp.tool()
def aide_assess_spec_document(
    markdown: str,
    artifact: str,
) -> dict[str, object]:
    """Run mechanical checks against a draft specification document.

    Args:
        markdown: Complete draft document content.
        artifact: requirements, design, or tasks.

    Returns:
        Heading, identifier, EARS, label, and draft-marker diagnostics.
    """
    return service.assess_document(markdown, artifact)


@mcp.tool()
def aide_read_spec_evidence(
    relative_path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict[str, object]:
    """Read an exact bounded range from an approved evidence document.

    Args:
        relative_path: Approved repository-relative Markdown path.
        start_line: One-based first line.
        end_line: Optional inclusive last line.

    Returns:
        Redacted content with an exact line citation.
    """
    return service.read_evidence(relative_path, start_line, end_line)


@mcp.tool()
def aide_refresh_spec_index() -> dict[str, object]:
    """Refresh only the in-memory documentation index."""
    return service.refresh()


def main() -> None:
    """Run the local specification MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
