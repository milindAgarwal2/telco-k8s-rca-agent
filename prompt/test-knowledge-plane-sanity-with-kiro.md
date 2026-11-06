# Kiro Prompt: Test a Shared Neo4j and Graphiti Knowledge Plane

Use this prompt after at least two related repositories have been ingested.
The test is read-only.

---

You are working in one member repository of a shared knowledge plane. Verify
that Kiro can resolve deterministic cross-service relationships from Neo4j and
use Graphiti for corroborating semantic and temporal context.

## Inputs

```text
PROJECT_ID: <current stable service ID>
KNOWLEDGE_PLANE_ID: <shared stable plane ID>
EXPECTED_PEER_SERVICES:
- <peer service ID>
QUESTION: <change request that crosses at least one declared service boundary>
TARGET_PATH: <repository-relative path in the current service>
MAX_RESULTS: 10
```

## Rules

1. Read `AGENTS.md` and applicable repository instructions.
2. Use only read-only Neo4j, Graphiti, repository, and Git operations. Do not
   ingest, add episodes, edit files, install software, or repair data.
3. Treat `knowledge-base/knowledge-plane.json` and exact `KB_*` relationships
   as reviewed topology. Treat Graphiti results as discovery context.
4. Verify consequential claims against the cited contract, source, or test.
5. Do not reveal credentials or raw environment values.

## Procedure

1. Read `knowledge-base/knowledge-plane.json`. Confirm its service ID and plane
   ID match the inputs and the redacted Spec Brain status.
2. Query Neo4j with bounded, parameterized Cypher. Confirm exactly one current
   `KB_Service`, one matching `KB_KnowledgePlane`, and a
   `REPRESENTS_SERVICE` edge from the current `KB_Repository`.
3. Traverse in both directions across `DEPENDS_ON_SERVICE`,
   `PROVIDES_INTERFACE`, `CONSUMES_INTERFACE`, `PUBLISHES_EVENT`, and
   `SUBSCRIBES_TO_EVENT`. Report stable IDs, relationship direction,
   declaration source, contract/schema paths, and whether each service has an
   ingested repository.
4. Confirm repository records use `<project-id>:` prefixes and shared topology
   uses `plane:<knowledge-plane-id>:` prefixes. Check for duplicate stable IDs,
   relationships with missing endpoints, and peer services from another plane.
5. Call the Graphiti status tool and require group
   `<knowledge-plane-id>-main`, unless the descriptor documents another shared
   group. Search the complete QUESTION. Confirm results are from the configured
   group and cite project-prefixed episodes from at least two member services.
6. Build bounded context for QUESTION and TARGET_PATH. Confirm exact service
   relationships appear before Graphiti facts; current-project paths remain
   scoped to PROJECT_ID; and term-matched primary context from a linked service
   is included when that repository has been ingested.
7. Open the referenced API/event contract and one relevant source or test from
   every implicated repository available in the workspace. Classify each
   retrieved claim as `VERIFIED`, `CONTRADICTED`, or `UNVERIFIED`.

## Result

Return:

- project, plane, Neo4j database, Graphiti database, and group;
- current service and peer service stable IDs;
- exact cross-service paths and their evidence;
- Graphiti facts and episode provenance;
- repository/contract/source corroboration;
- missing repositories, stale descriptors, unresolved peers, or scope leaks;
- status `PASS`, `WARN`, or `FAIL`.

Use `PASS` only when the exact topology is collision-free, the shared Graphiti
group returns multi-service context, and the code-generation context preserves
authority and project scope.
