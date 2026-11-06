# AIDE Architecture MCP

`aide-architecture-mcp` is a local, read-only Model Context Protocol (MCP)
server that prepares architecture evidence for Kiro. It specializes the shared
AIDE knowledge retrieval engine into explicit High-Level Design (HLD),
Low-Level Design (LLD), specification-relationship, folder-specification, and
OpenWiki views.

## Evidence model

The server uses this order:

1. Repository source, schemas, and tests remain authoritative.
2. Reviewed specifications describe intended behavior.
3. `knowledge-base/HLD.md`, `knowledge-base/LLD.md`, folder specifications,
   and the specification relationship map are primary architecture context.
4. `openwiki/` pages are secondary explanation and navigation.

All documentation is treated as draft unless it explicitly records subject
matter expert (SME) review. Static dependency evidence is never presented as
proof of a runtime call.

## Architecture tools

| Tool | Purpose |
|---|---|
| `aide_architecture_status` | Report source health, counts, views, and limits. |
| `aide_search_architecture` | Search and classify HLD, LLD, relationship, specification, and OpenWiki evidence. |
| `aide_build_architecture_context` | Build bounded evidence for HLD, LLD, or combined design work. |
| `aide_trace_architecture_relationships` | Find declared parents, children, dependencies, consumers, interfaces, and flows. |
| `aide_read_architecture_evidence` | Read an exact bounded Markdown line range. |
| `aide_refresh_architecture_index` | Rebuild only the process-local index. |

Architecture context also reports missing expected evidence and supplies a
review checklist for boundaries, contracts, flows, failures, configuration,
resource ownership, affected tests, and unresolved questions.

## Setup and verification

From the repository root:

```powershell
uv sync --project aide-architecture-mcp
```

From `aide-architecture-mcp/`:

```powershell
uv run --offline --frozen python -m pytest
uv run --offline --frozen ruff check .
```

Run the server directly:

```powershell
uv run --project aide-architecture-mcp --offline --frozen aide-architecture-mcp
```

The architecture package depends on the sibling `aide-knowledge-mcp` package
through a locked local editable dependency. Query-time execution uses no model,
database, network service, Neo4j, or Graphiti.

## Environment variables

| Variable | Default | Purpose |
|---|---:|---|
| `AIDE_ARCHITECTURE_ROOT` | Inferred repository root | Repository read boundary. |
| `AIDE_ARCHITECTURE_PRIMARY_DIR` | `knowledge-base` | Primary architecture source. |
| `AIDE_ARCHITECTURE_SECONDARY_DIR` | `openwiki` | Secondary architecture source. |
| `AIDE_ARCHITECTURE_MAX_FILE_BYTES` | `4000000` | Maximum indexed Markdown file size. |
| `AIDE_ARCHITECTURE_MAX_SECTION_CHARS` | `12000` | Maximum lexical section fragment size. |
| `AIDE_ARCHITECTURE_MAX_EXCERPT_CHARS` | `1800` | Maximum result excerpt size. |
| `AIDE_ARCHITECTURE_MAX_READ_LINES` | `500` | Maximum lines returned by an exact read. |
| `AIDE_ARCHITECTURE_MAX_CONTEXT_CHARS` | `40000` | Maximum composed context size. |

Every configured directory must resolve inside the repository. Invalid roots,
traversal, symlinks, non-Markdown reads, and oversized output requests fail
closed.

## Current boundary

Relationship tracing is deterministic retrieval from the Markdown relationship
map. It is not Neo4j graph traversal and does not claim runtime behavior beyond
the cited documentation. Graph-backed enrichment can be added later without
changing the primary/secondary evidence contract.

