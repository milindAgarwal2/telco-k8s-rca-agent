# Specification Brain

Specification Brain is a repository-neutral knowledge layer for Kiro. It
projects reviewed Markdown and source references into deterministic `KB_*`
Neo4j records and can add Graphiti semantic and temporal memory from the same
canonical manifest.

The baseline installs the runtime under `.aide/full/spec-brain`; it never adds
dependencies to the target application.

## Authority order

1. current source, schemas, configuration, and focused tests;
2. reviewed `knowledge-base/` and relevant folder `SPECS.md` files;
3. deterministic Neo4j `KB_*` relationships;
4. Graphiti facts with group, episode, and temporal provenance; and
5. generated OpenWiki pages as secondary navigation.

Graph data assists discovery. It does not supersede current repository evidence
or human review.

## Repository-neutral discovery

`build-manifest --scope full` discovers existing HLD, LLD, relationship maps,
repository-owned `SPECS.md` files, OpenWiki pages, and claim sidecars. It ignores
common dependency, build, virtual-environment, and AIDE installation folders.
When curated knowledge is absent, a root `README.md` can seed a small initial
manifest.

Identifiers use `SPEC_BRAIN_PROJECT_ID`. If it is absent, a safe value is
derived from `SPEC_BRAIN_ROOT` or the repository directory name. Set it
explicitly when multiple workstations or checkouts must share stable IDs.

## Configuration

| Variable | Purpose |
| --- | --- |
| `SPEC_BRAIN_ROOT` | Target repository root; normally `.`. |
| `SPEC_BRAIN_PROJECT_ID` | Optional stable project namespace. |
| `NEO4J_URI` | Neo4j Bolt or routing URI. |
| `NEO4J_USER` or `NEO4J_USERNAME` | Neo4j user. |
| `NEO4J_PASSWORD` | Neo4j password, supplied outside Git. |
| `NEO4J_KB_DATABASE` | Exact graph database; defaults to `neo4j`. |
| `NEO4J_GRAPHITI_DATABASE` | Graphiti database; defaults to `neo4j`. |
| `GRAPHITI_GROUP_ID` | Semantic partition; defaults to `<project-id>-main`. |
| `INTERNAL_MODEL_AUTH` | `bearer-token` or `azure-identity`. |
| `INTERNAL_LLM_BASE_URL` / `INTERNAL_LLM_MODEL` | Approved OpenAI-compatible LLM service. |
| `INTERNAL_LLM_TOKEN` | Token for bearer-token mode only. |
| `INTERNAL_AZURE_TOKEN_SCOPE` | Token scope for Azure identity mode. |
| `INTERNAL_EMBEDDING_BASE_URL` / `INTERNAL_EMBEDDING_MODEL` | Approved embedding service. |
| `INTERNAL_EMBEDDING_DIMENSION` | Stored vector dimension. |
| `SPEC_BRAIN_MAX_CONTEXT_TOKENS` | Required context budget. |
| `SPEC_BRAIN_MAX_SEMANTIC_RESULTS` | Semantic result limit; default `12`. |
| `SPEC_BRAIN_MAX_RELATIONSHIP_DEPTH` | Exact expansion depth; default `2`. |

Neo4j Community deployments normally use `neo4j` for both database variables.
Separate projects by stable IDs and Graphiti group; database-side permissions
remain the authorization boundary.

## Commands

Prepare the frozen runtime:

```text
uv sync --project .aide/full/spec-brain --all-groups --frozen
```

Validate redacted configuration and service health:

```text
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain check-config --component query
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain check-services
```

Build a deterministic manifest:

```text
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain build-manifest --root . --scope pilot --output <temporary-manifest.jsonl>
```

Use `--scope full` after reviewing the pilot. Exact and semantic ingestion are
explicit mutating commands and require separate authorization:

```text
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain load-exact --manifest <manifest.jsonl>
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain load-graphiti --manifest <manifest.jsonl> --reference-time <ISO-8601-time> --smoke
```

The workspace `graphiti` MCP launches `aide-spec-brain-mcp` and exposes only:

- `spec_brain_graphiti_status`;
- `spec_brain_graphiti_health`;
- `spec_brain_search_graphiti`; and
- `spec_brain_build_context`.

It exposes no ingestion, create, update, delete, clear, or schema-management
tool. The packaged MCP entry is disabled until the project owner configures and
reviews its local environment.

See `GRAPHITI_KIRO_NEO4J_SETUP.md` for hosted and local model profiles.
