# `tools/spec_brain` Folder Specification

## tntent and significance

This folder owns the repository-local specification-brain tool. tt converts
primary knowledge-base documents, folder specifications, relationship maps,
and secondary OpenWiki evidence into exact Neo4j data and Graphiti semantic
episodes, then returns a bounded context package for Kiro. tt also exposes
read-only Graphiti search and combined context through a workspace MCP server.
Operational guidance in this folder documents both the validated hosted-model
profile and a resource-bounded local Ollama profile.

It is deliberately outside application source; none of its behavior participates in runtime
serving.

## tnputs and outputs

tnputs are explicit Markdown paths, OpenWiki claim JSON, process environment
configuration, a designated Neo4j database, approved model services, and a
user's specification request. Outputs are canonical JSON Lines manifests,
additive graph records, semantic episodes, JSON or Markdown context, and setup
guidance for supported deployment profiles.

## Contracts

- Parse Markdown once and share the canonical manifest between both loaders.
- Preserve complete tables, lists, and fenced diagrams within their sections.
- Keep folder dependency direction as consumer → dependency.
- Keep OpenWiki sidecars read-only and retain their existing claim IDs.
- Use stable IDs and additive `MERGE` operations; never delete unrelated graph
  data.
- Require explicit service configuration and stop before semantic mutation when
  a dependency is unavailable.
- Disable Graphiti telemetry and never activate a provider default.
- Order context primary → exact → source/tests → semantic → secondary.
- Fail when the smallest useful package cannot fit the context ceiling.
- Expose only status, health, semantic search, and combined-context MCP tools;
  graph mutation is never part of the workspace MCP surface.
- Bind every Graphiti MCP search to the configured database and group ID.
- In Azure Foundry Entra mode, use the resource `/openai/v1` endpoint for
  both OpenAI-compatible clients, use deployment names as model identifiers,
  acquire tokens with `DefaultAzureCredential` for
  `https://ai.azure.com/.default`, and require no static model token.
- Keep the configured embedding dimension and deployment compatible with
  embeddings already stored in Neo4j.
- Use Graphiti's generic OpenAI-compatible client for local Ollama inference;
  changing only the endpoint of the OpenAI-specific client is insufficient.
- Isolate deployment profiles when their embedding models or vector dimensions
  differ, and regenerate semantic embeddings from source episodes rather than
  copying incompatible vectors.

## tnteraction points

| Direction | Folder or service | tnteraction |
|---|---|---|
| Parent | `tools/` | Developer-tool aggregation boundary |
| tnput | `knowledge-base/` | Primary HLD, LLD, and relationship map |
| tnput | repository `SPECS.md` files | Primary folder contracts |
| tnput | `openwiki/` | Secondary pages and evidence claims |
| Consumer | `.kiro/skills/spec-brain/` | Retrieval-first specification workflow |
| Consumer | `.kiro/settings/mcp.json` | Workspace Graphiti MCP launcher |
| External | Neo4j | Exact and Graphiti-managed graph storage |
| External | approved internal endpoints | Language-model, embedding, optional reranking |
| External | optional local Ollama service | OpenAI-compatible local language-model and embedding APIs |

## Error and resource handling

Configuration, parsing, service, ingestion, retrieval, and budget errors are
explicit. Drivers and compatible-model clients are closed by their owning
lifecycle. Graphiti episodes are sequential and resumable; a failed episode
does not cause deletion of earlier successful episodes.

The canonical manifest and context package are bounded host-memory objects.
Neo4j sessions own network resources for one operation. Graphiti owns semantic
entity and edge memory in the configured database and stable group.

## Environment variables

See [README.md](README.md) for the complete configuration table. Secrets are
process inputs and must never be stored in repository files.

## Verification

Focused unit tests live in `tests/`. Live ingestion is an explicit operator
action and is not part of ordinary unit tests.



