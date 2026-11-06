# AIDE Specification Brain runtime

This optional project-local runtime provides deterministic Neo4j ingestion,
Graphiti semantic and temporal ingestion, and a read-only Kiro MCP surface.
It is independent of the target application's language and dependency files.

The installer places it at `.aide/full/spec-brain`. Prepare its frozen
environment with `uv sync --project .aide/full/spec-brain --all-groups
--frozen`. Configure credentials and model endpoints in the local process
environment. Never write them to the repository.

`SPEC_BRAIN_PROJECT_ID` is optional. When absent, the runtime derives a safe
namespace from `SPEC_BRAIN_ROOT` or the repository directory name. Set it
explicitly when multiple checkouts must share stable graph identifiers.

## Shared knowledge plane

Copy `.aide/templates/knowledge-plane.json` to
`knowledge-base/knowledge-plane.json`, replace every placeholder, and review it
with the service owners. `service.id` must equal `SPEC_BRAIN_PROJECT_ID`.
Related repositories use distinct project IDs and the same
`knowledge_plane` value. The runtime creates globally stable `KB_Service`,
`KB_Interface`, and `KB_Event` nodes plus evidence-bearing relationships, so
independent ingestion runs converge in one Neo4j database.

Set `SPEC_BRAIN_KNOWLEDGE_PLANE_ID` to the descriptor's `knowledge_plane`
value. When that variable is absent, the runtime reads the descriptor under
`SPEC_BRAIN_ROOT`; otherwise it falls back to the project ID. The default
Graphiti group is `<knowledge-plane-id>-main`. Sharing that group lets Graphiti
extract semantic relationships across member services while project-prefixed
episode names remain collision-safe.

The exact retriever anchors repository paths to the active project. It follows
the service topology to include term-matched primary context from linked
projects and returns the exact service relationships separately from semantic
facts. A missing descriptor preserves isolated single-repository behavior.

The workspace MCP exposes status, health, semantic search, and combined
context operations. It exposes no mutation tools. Graph ingestion is available
only through the explicit `aide-spec-brain` command and therefore remains a
separately authorized operation.

See `tools/spec_brain/GRAPHITI_KIRO_NEO4J_SETUP.md` for hosted
OpenAI-compatible and local Ollama configurations.
