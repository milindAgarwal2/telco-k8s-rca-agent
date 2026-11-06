---
name: aide-knowledge-graph
description: Create, refresh, curate, query, and explain a repository knowledge system across OpenWiki, reviewed Markdown, Neo4j, and Graphiti. Use for plain-language knowledge-base or knowledge-graph requests in a Full AIDE workspace.
---

# AIDE knowledge-graph engineering

Translate the user's plain-language intent into the smallest useful knowledge
operation. Read `.aide/workflows/definitions/manage-knowledge-graph.md` for a
create, update, cross-service link, or ingestion run. Read-only questions can
use the query path below without running the mutation phases.

## Start with a layer inventory

Resolve the Git root and applicable instructions. Record the branch, `HEAD`,
worktree status, and requested scope. Inspect these layers without assuming
that installed configuration is connected:

| Layer | Healthy evidence |
| --- | --- |
| Source | Current code, schemas, configuration, focused tests, and revision |
| OpenWiki | Valid `openwiki/` plus a completed or resumable MCP lifecycle |
| Local knowledge | Reviewed HLD, LLD, relationship map, knowledge-plane descriptor, and useful folder `SPECS.md` files |
| Exact graph | Expected `KB_*` schema, project/plane records, stable IDs, provenance, and no duplicate IDs |
| Graphiti | Read-only status, expected database/group, configured semantic services, and a successful group-scoped query |
| Shared plane | Reviewed service/interface/event contracts with unambiguous owners and directions |

Report absent, present, stale, draft, unavailable, and healthy separately.
Do not ask the user to understand these terms before beginning useful discovery.

## Route by intent

- **Question or explain:** retrieve the narrowest context in authority order and
  answer. Do not regenerate or ingest.
- **Create or bootstrap:** build missing local layers, obtain review, then
  prepare configured graph layers.
- **Update, maintain, or curate:** compare provenance and source revision;
  refresh only affected content and derived views.
- **Design:** prepare a candidate knowledge-plane descriptor and relationship
  model. Stop for review before ingestion.
- **Implement or ingest:** use only reviewed inputs, deterministic manifests,
  additive loaders, and an exact target binding.

## OpenWiki and local knowledge

Use the `openwiki` skill and MCP lifecycle for initialization, resume, and
update. Do not use direct generation commands or hand-edit OpenWiki-owned
indexes, `.claims`, run state, provenance, or logs. If the command, MCP, or
provider is unavailable, preserve state and name the documented installation
or configuration step; do not switch provider.

For local knowledge, use current repository evidence and the established
prompts under `prompt/` for HLD, LLD, folder specifications, relationship map,
and OpenWiki refinement. Preserve existing reviewed meaning, stable anchors,
and project-owned files. Mark generated or inferred content as draft and list
the source paths that support it.

## Exact Neo4j graph

The workspace `neo4j` MCP is for bounded read-only schema and Cypher queries.
Create or update the exact graph only through the packaged Spec Brain manifest
builder and `load-exact` procedure documented in
`prompt/populate-neo4j-knowledge-base-with-kiro.md`.

Use `knowledge-base/knowledge-plane.json` as the reviewed topology contract.
If it is absent, copy `.aide/templates/knowledge-plane.json`, fill only values
supported by repository evidence, and stop for review. A repository uses one
stable lowercase project ID; related repositories use one stable knowledge
plane ID. Repository records use the project prefix. Shared topology records
use `plane:<knowledge-plane-id>:`. Reuse identifiers already present in Neo4j.
Never derive identity from a temporary branch or absolute workstation path.

Build the manifest twice and require matching hashes before ingestion. Exact
loads are additive `MERGE` upserts. Never run `DELETE`, `DETACH DELETE`,
`DROP`, graph reset, database replacement, or unrestricted write Cypher.

## Cross-service linking

Inventory existing `KB_KnowledgePlane`, `KB_Service`, `KB_Interface`, and
`KB_Event` records before proposing a link.

- Same reviewed plane plus the same stable interface or event ID and local
  contract evidence: prepare the descriptor relationship.
- Same plane but ambiguous owner, direction, or ID: show candidates and ask one
  focused question.
- Different or missing plane membership: propose the plane decision and stop.
- Graphiti similarity or similar names only: show as a possible lead; never
  create an exact edge.

When a peer repository has not been ingested, keep it as a declared external
service reference. Do not scan unrelated graph bodies or infer authorization
from database visibility.

## Graphiti contextual memory

Start with `spec_brain_graphiti_status`; use health only when creation or update
requires provider access. Require read-only MCP mode, no mutation tools, the
expected Neo4j database and Graphiti group, and configured semantic services.
Use `spec_brain_search_graphiti` for semantic discovery and
`spec_brain_build_context` for a bounded combined answer.

Ingest only through the packaged `load-graphiti` procedure, using the same
verified manifest, stable group, and one recorded reference time. Never write
Graphiti-owned nodes or relationships with Cypher and never substitute the
generic `memory` MCP. Similarity is a discovery lead, not proof.

## Query and explain

Compose answers in this order: reviewed local knowledge, exact service/module
relationships, cited source and tests, Graphiti semantic context, then
secondary OpenWiki. Verify consequential graph claims against the current
checkout. Label contradictions and missing evidence.

Explain the answer without graph jargon first. Then render only the relevant
subgraph as Mermaid. Include stable identifiers when useful, edge direction,
and a short provenance list. For larger exploration, provide a parameterized,
bounded read-only Cypher query for Neo4j Browser and link to
`openwiki/index.md`. Do not start a visualization server automatically.

## Completion

Return a layer-status table, project/plane namespace, graph target and group,
source revision, changed files, manifest hash when built, validation question,
focused diagram, unresolved link decisions, and a safe resume action. Use
`READY`, `READY_WITH_GAPS`, `REVIEW_REQUIRED`, `PARTIAL`, or `BLOCKED`. Never
claim a layer is ready without its stated health evidence.
