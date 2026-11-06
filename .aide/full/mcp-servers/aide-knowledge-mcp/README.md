# AIDE Knowledge MCP

`aide-knowledge-mcp` is a local, read-only Model Context Protocol (MCP)
server for engineering knowledge in this repository. It gives Kiro a bounded,
citation-bearing retrieval layer without sending repository content to a
model or external service.

## Authority and source precedence

The server enforces this documentation order:

1. `knowledge-base/` is primary architecture and specification context.
2. `openwiki/` is secondary explanation and navigation.

Repository source, schemas, and tests remain more authoritative than either
documentation source. Generated documentation remains draft until reviewed by
a subject matter expert (SME). A secondary result never silently overrides a
primary result.

## Tools

| Tool | Purpose |
|---|---|
| `aide_knowledge_status` | Show source health, index counts, limits, and warnings. |
| `aide_search_knowledge` | Search both tiers and return primary results first. |
| `aide_build_knowledge_context` | Compose bounded context for requirements, design, or tasks. |
| `aide_read_knowledge_document` | Read an exact, bounded Markdown line range. |
| `aide_list_knowledge_documents` | List indexed documents by source and path prefix. |
| `aide_refresh_knowledge_index` | Refresh only the in-memory index. |

Every content result includes its repository path, heading, line range,
source tier, draft status, and citation.

## Retrieval behavior

- Markdown files are indexed lazily and refreshed when file metadata changes.
- Search is deterministic lexical retrieval; it calls no language model.
- Approximately 75 percent of a mixed result set is reserved for primary
  knowledge when matching primary evidence exists.
- Oversized sections are split on line boundaries without splitting fenced
  code blocks.
- Tool output is bounded by result, line, file-size, and character limits.
- Common token and credential forms are redacted before indexing or returning
  content.
- Absolute paths, traversal, symlinked files, non-Markdown files, and paths
  outside the two configured roots are rejected.

## Setup

From the repository root:

```powershell
uv sync --project aide-knowledge-mcp
uv run --project aide-knowledge-mcp --frozen python -m pytest
uv run --project aide-knowledge-mcp --frozen ruff check .
```

Run the server directly:

```powershell
uv run --project aide-knowledge-mcp --offline --frozen aide-knowledge-mcp
```

The committed lock file and synchronized local environment make later Kiro
startup offline-capable. Initial dependency resolution may require access to
the configured Python package registry.

## Kiro workspace configuration

The workspace MCP definition uses the following shape:

```json
{
  "mcpServers": {
    "aide-knowledge-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        ".aide/full/mcp-servers/aide-knowledge-mcp",
        "--offline",
        "--frozen",
        "aide-knowledge-mcp"
      ],
      "env": {
        "AIDE_KNOWLEDGE_ROOT": "."
      },
      "timeout": 120000,
      "requestTimeout": 120000,
      "disabled": false
    }
  }
}
```

Do not add this server to `autoApprove`; reading repository knowledge should
remain an explicit agent action.

## Configuration

| Environment variable | Default | Contract |
|---|---:|---|
| `AIDE_KNOWLEDGE_ROOT` | Inferred repository root | Must be an existing directory. |
| `AIDE_KNOWLEDGE_PRIMARY_DIR` | `knowledge-base` | Must resolve inside the repository. |
| `AIDE_KNOWLEDGE_SECONDARY_DIR` | `openwiki` | Must resolve inside the repository. |
| `AIDE_KNOWLEDGE_MAX_FILE_BYTES` | `4000000` | Per-document indexing ceiling. |
| `AIDE_KNOWLEDGE_MAX_SECTION_CHARS` | `12000` | Search-section chunk ceiling. |
| `AIDE_KNOWLEDGE_MAX_EXCERPT_CHARS` | `1600` | Per-result excerpt ceiling. |
| `AIDE_KNOWLEDGE_MAX_READ_LINES` | `400` | Per-call line-read ceiling. |
| `AIDE_KNOWLEDGE_MAX_CONTEXT_CHARS` | `30000` | Composed Markdown ceiling. |

Invalid roots or limits fail server startup. Unreadable or oversized individual
documents produce explicit index warnings and do not make partial content look
successful.

## Current boundary

This first version intentionally does not query Neo4j, Graphiti, source code,
tests, external model providers, or the network. Neo4j/Graphiti enrichment can
be added later behind a distinct optional adapter while retaining the same
primary/secondary output contract.


