# Graphiti, Kiro, and Neo4j Setup Guide

This guide configures the AIDE Specification Brain for any repository and
language stack. The application can use Java, Kotlin, Go, Python, PHP, Rust,
JavaScript, TypeScript, Angular, Bash, Kubernetes, GitOps, FluxCD, or a mixed
monorepo; the graph runtime remains isolated under `.aide/full/spec-brain`.

## Architecture

```text
Kiro
  -> read-only workspace Graphiti MCP
     -> Specification Brain
        -> exact KB_* retrieval in Neo4j
        -> Graphiti semantic and temporal retrieval
           -> approved LLM
           -> approved embedding model
           -> Neo4j
```

Graph ingestion is a separate CLI action. The MCP server exposes retrieval only.
Source and tests remain authoritative, followed by reviewed knowledge-base
content, exact graph relationships, Graphiti facts, and OpenWiki navigation.

## Common setup

1. Install `uv`, a supported Python version, Neo4j 5.26 or later, and Kiro.
2. Apply the AIDE full overlay.
3. Prepare the isolated runtime:

   ```text
   uv sync --project .aide/full/spec-brain --all-groups --frozen
   ```

4. Set `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD` outside Git.
5. Optionally set `SPEC_BRAIN_PROJECT_ID`; otherwise the repository directory
   supplies the namespace. Use a stable explicit value for shared graphs.
6. Set both Neo4j database variables to `neo4j` for Community Edition.
7. Configure one of the model profiles below.
8. Review `.kiro/settings/mcp.json`, approve only the required environment
   variable names in Kiro, and enable the packaged `graphiti` server.

Never store credentials, bearer tokens, private endpoints, or production data
in the baseline or target repository.

## Profile 1: hosted OpenAI-compatible models

Use any organization-approved OpenAI-compatible endpoint. Azure identity and
bearer-token authentication are supported.

```text
SPEC_BRAIN_ROOT=.
SPEC_BRAIN_PROJECT_ID=<stable-project-id>
SPEC_BRAIN_KNOWLEDGE_PLANE_ID=<stable-shared-plane-id>
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<external-secret>
NEO4J_KB_DATABASE=neo4j
NEO4J_GRAPHITI_DATABASE=neo4j
GRAPHITI_GROUP_ID=<stable-shared-plane-id>-main
INTERNAL_MODEL_AUTH=azure-identity
INTERNAL_LLM_BASE_URL=https://<approved-host>/openai/v1
INTERNAL_LLM_MODEL=<deployment-name>
INTERNAL_EMBEDDING_BASE_URL=https://<approved-host>/openai/v1
INTERNAL_EMBEDDING_MODEL=<embedding-deployment>
INTERNAL_EMBEDDING_DIMENSION=<model-dimension>
INTERNAL_AZURE_TOKEN_SCOPE=https://ai.azure.com/.default
SPEC_BRAIN_MAX_CONTEXT_TOKENS=12000
```

For bearer-token mode, set `INTERNAL_MODEL_AUTH=bearer-token` and supply
`INTERNAL_LLM_TOKEN` through an approved secret mechanism. Confirm that the
endpoint, model names, data handling, and identity permissions are approved.

## Profile 2: local Ollama models

Use an Ollama LLM and embedding model that fit the workstation's available RAM,
CPU, and GPU memory. Begin with a smaller instruct model such as Mistral 7B or
Llama 3.1 8B and an embedding model whose dimension is known.

```text
SPEC_BRAIN_ROOT=.
SPEC_BRAIN_PROJECT_ID=<stable-project-id>
SPEC_BRAIN_KNOWLEDGE_PLANE_ID=<stable-shared-plane-id>
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<external-secret>
NEO4J_KB_DATABASE=neo4j
NEO4J_GRAPHITI_DATABASE=neo4j
GRAPHITI_GROUP_ID=<stable-shared-plane-id>-ollama
INTERNAL_MODEL_AUTH=bearer-token
INTERNAL_LLM_BASE_URL=http://localhost:11434/v1
INTERNAL_LLM_MODEL=<ollama-llm>
INTERNAL_LLM_TOKEN=ollama-local
INTERNAL_EMBEDDING_BASE_URL=http://localhost:11434/v1
INTERNAL_EMBEDDING_MODEL=<ollama-embedding-model>
INTERNAL_EMBEDDING_DIMENSION=<model-dimension>
SPEC_BRAIN_MAX_CONTEXT_TOKENS=8000
```

Validate that the chosen Ollama models support the OpenAI-compatible operations
used by Graphiti. Reduce context and result limits when the workstation is
resource constrained.

Do not reuse a Graphiti vector index with a different embedding dimension.
Use a separate database, DBMS instance, or reviewed graph reset procedure when
changing embedding models.

## Validation and ingestion

Run configuration and dependency checks first:

```text
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain check-config --component query
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain check-services
```

Build and inspect a pilot manifest before any graph write:

```text
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain build-manifest --root . --scope pilot --output <temporary-manifest.jsonl>
```

After approval, load exact records and a two-episode Graphiti smoke set. Supply
a timezone-aware reference time and preserve the manifest hash and project/group
identifiers as evidence.

Use the packaged Neo4j and Graphiti sanity prompts after ingestion. A successful
Neo4j query proves exact graph access; a successful group-scoped Graphiti search
with episode and temporal provenance proves Graphiti access.

## Troubleshooting order

1. Confirm Neo4j is reachable and the database user has the intended role.
2. Run `check-config`; resolve only the redacted missing variable names.
3. Run `check-services`; do not repair or install from inside a Kiro test prompt.
4. Call `spec_brain_graphiti_status`, then health, then bounded search.
5. Confirm project ID, group ID, database, embedding model, and dimension match
   the values used during ingestion.
6. Re-ingest only when the corpus or intended temporal facts changed. Reinstall
   only when the packaged runtime or lock changed.

Graphiti group IDs organize facts but do not replace database authorization.
Use database and service controls for isolation.
