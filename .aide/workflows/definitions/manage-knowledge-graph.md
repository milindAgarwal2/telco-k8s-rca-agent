# Workflow: Knowledge-Graph Engineering

## Metadata

- Workflow ID: `aide-knowledge-graph-engineering`
- Trigger: a user asks to create, update, maintain, curate, design, implement,
  query, or visualize repository knowledge.
- Specialist: `aide-knowledge-graph`
- Status: reusable Full-flavor protocol with read-only degradation.

## Objective

Turn ordinary user intent into a source-linked knowledge system consisting of
OpenWiki, reviewed local knowledge, an exact Neo4j projection, and optional
Graphiti contextual memory. Keep each layer independently usable and make the
result understandable to a user who does not know graph terminology.

## Entry behavior

Begin with read-only discovery. Classify the request as `QUERY`, `CREATE`,
`UPDATE`, `CURATE`, `DESIGN`, `INGEST`, or `LINK`. Infer obvious scope from the
active repository. Ask only when an unresolved decision changes the stable
project ID, shared knowledge-plane membership, relationship ownership or
direction, external provider, database/group target, or mutation scope.

`QUERY` follows Phases 1, 5, and 6 and performs no writes. Other modes proceed
only through the phases needed by the current layer status.

## Authority order

1. Current source, schemas, configuration, and focused tests establish
   implemented behavior.
2. Reviewed specifications and `knowledge-base/` establish approved design.
3. Folder `SPECS.md` and the relationship map provide maintained structure.
4. Exact `KB_*` graph records provide deterministic relationships and
   provenance.
5. Graphiti provides semantic and temporal discovery context.
6. OpenWiki provides generated navigation and explanation.

When sources disagree, report the contradiction; do not blend them into a new
fact. Never ingest credentials, personal data, production records, binaries,
large logs, generated dependencies, or arbitrary source bodies.

## Phase 1: Repository and layer inventory

Record the Git root, applicable instructions, branch, HEAD, dirty paths, project
profiles, requested scope, and excluded or sensitive paths. Inspect:

- OpenWiki command/MCP status, `openwiki/`, lifecycle state, and index;
- HLD, LLD, relationship map, knowledge-plane descriptor, and folder specs;
- workspace Neo4j and Graphiti entries without reading secrets;
- Spec Brain runtime and redacted configuration;
- existing graph databases, `KB_*` labels, project/plane IDs, Graphiti group,
  and other visible service graphs through bounded read-only queries.

Output a layer-status table. Installed, configured, connected, populated,
reviewed, and healthy are distinct states.

## Phase 2: OpenWiki

If `openwiki/` is absent in a create request, initialize it through the
OpenWiki skill's resumable MCP lifecycle. If present and the update request or
source provenance shows drift, run the update lifecycle. If it is current,
preserve it. Never hand-edit OpenWiki-owned indexes, claims, run state,
provenance, or logs.

If the approved OpenWiki command, MCP, or provider is missing, report the exact
setup gap and preserve all state. Do not install from an unreviewed source,
switch providers, or block an independent read-only answer from local evidence.

## Phase 3: Local knowledge corpus

Inspect `knowledge-base/HLD.md`, `knowledge-base/LLD.md`,
`knowledge-base/SPECS-RELATIONSHIP-MAP.md`,
`knowledge-base/knowledge-plane.json`, and useful folder `SPECS.md` files.
Create missing candidates or update affected sections from current source,
schemas, configuration, and tests. Use existing repository-neutral prompts and
preserve reviewed content, stable identifiers, anchors, and unrelated files.

Every changed claim records evidence and whether it is direct, inferred,
historical, proposed, or unresolved. The relationship map must not invent an
edge to make the graph look complete.

### Gate A: local knowledge and topology review

Before graph ingestion, present the exact candidate paths and revision, project
ID, knowledge-plane ID, service/interface/event identifiers, cross-service
relationships, inferred claims, and unresolved questions. New or substantively
changed content remains draft until the user or named reviewer accepts it.

## Phase 4: Deterministic graph preparation and load

Use `prompt/populate-neo4j-knowledge-base-with-kiro.md` and the packaged Spec
Brain runtime. Validate redacted configuration and the reviewed descriptor.
Build the selected manifest twice; require equal SHA-256 hashes. Verify stable
IDs, relationship endpoints, source paths, authority metadata, namespace, and
sensitive-data exclusion.

Inspect existing knowledge planes and services first. Repository records use
the stable project prefix; shared service/interface/event records use the
`plane:<knowledge-plane-id>:` prefix. If an existing project graph uses another
identifier, preserve it and stop for reconciliation rather than duplicating it.

### Gate B: exact graph target

Before `load-exact`, bind the accepted manifest hash, source revision, Neo4j
database, project ID, knowledge-plane ID, operation target, and additive-only
behavior to the existing approval and tool-permission gate. A general request
authorizes preparation; it does not resolve an ambiguous shared target.

Run the additive loader once and repeat with the same manifest as an idempotency
check. Query for duplicate stable IDs, missing endpoints, provenance, and the
expected project/plane records. Preserve the previous graph on failure. Never
delete, reset, replace, or issue ad hoc write Cypher.

## Phase 5: Cross-service and Graphiti context

For every proposed cross-service edge, require a reviewed descriptor plus a
stable interface/event/contract identity and direction. When another graph is
visible but the relationship is uncertain, show only the relevant candidate
services and evidence, ask one focused question, and stop that edge. Similarity
or name matching alone cannot create an exact relationship.

If Graphiti is configured, verify `spec_brain_graphiti_status`, health, expected
database/group, semantic provider presence, and read-only MCP surface. Ingest
through `load-graphiti` with the accepted manifest and one recorded reference
time. Resume with the same manifest/time after a partial failure. Do not use
manual Graphiti Cypher or the generic memory MCP.

If Graphiti is absent or unhealthy, leave the exact graph usable and report
`READY_WITH_GAPS` or `PARTIAL` rather than pretending semantic memory worked.

## Phase 6: Retrieval validation and visualization

Ask one representative question from the user's intent. Retrieve a bounded
context package in authority order and verify consequential results against
current source or tests. Report useful results, missing evidence, context-budget
limits, and contradictions.

Answer in plain language. Render a focused Mermaid diagram of only the nodes
and directed edges needed for the answer, with a short legend and provenance.
For larger exploration, provide a bounded parameterized read-only Cypher query
for Neo4j Browser. Link `openwiki/index.md` for broader navigation. Do not start
OpenWiki visualization or another local server automatically.

## Failure and resumption

Preserve all existing local and graph layers. Record the source revision,
candidate revision, accepted manifest hash, exact target, reference time, last
successful phase, failed tool or command, and retry precondition. Never retry
an uncertain mutation with changed inputs. Re-inventory changed upstream inputs
and invalidate their derived phases.

## Completion states

- `READY`: requested layers are healthy and the validation question passed.
- `READY_WITH_GAPS`: usable requested result with an explicitly unavailable
  optional layer such as Graphiti.
- `REVIEW_REQUIRED`: local content or topology needs a human decision.
- `PARTIAL`: a mutation stopped after a known subset while prior state remains.
- `BLOCKED`: a mandatory dependency, target, permission, or evidence item is
  missing.

The final report includes the layer table, source revision, changed paths,
project and plane IDs, database/group, manifest hash, load/idempotency results,
relationship decisions, validation query, diagram, unresolved gaps, and exact
resume action.
