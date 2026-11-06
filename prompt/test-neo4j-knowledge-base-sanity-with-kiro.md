# Kiro Prompt: Test Neo4j Knowledge-Base Sanity

Copy the prompt below into Kiro after populating the repository knowledge graph.
Select one profile and replace the sample input values.

---

You are working in the current repository. Perform a read-only sanity test of
the populated knowledge base using one of two profiles:

1. `neo4j`: validate the exact `KB_*` graph and deterministic contextual
   retrieval; or
2. `neo4j-graphiti`: run every exact-graph check, then validate Graphiti
   semantic and temporal context.

Do not modify either graph, the repository, OpenWiki, or the knowledge base.
Do not silently downgrade the selected profile when a dependency is missing.

## Sample input

```text
PROFILE: neo4j
PROJECT_ID: <configured or repository-derived project ID>
TARGET_PATH: <repository-relative component path>
QUESTION: <concrete architecture or behavior question>
PARAPHRASE: <semantically equivalent wording of QUESTION>
MAX_RESULTS: 20
EXPECTED_CORPUS_SCOPE: full
EXPECTED_MANIFEST_SHA256: <optional hash from ingestion report>
CONTEXT_OUTPUT: <temporary JSON output path>
```

Allowed profiles are `neo4j` and `neo4j-graphiti`. Require one
Graphiti-safe `PROJECT_ID`, one
repository-relative `TARGET_PATH`, a concrete `QUESTION`, a semantically
equivalent `PARAPHRASE`, and `MAX_RESULTS` from 1 through 50.

## Evidence rules

Use this authority order:

1. current source, schemas, configuration, build definitions, and focused
   tests establish implemented behavior;
2. reviewed `knowledge-base/` and folder `SPECS.md` files provide primary
   architecture and contract context;
3. exact Neo4j nodes and relationships provide deterministic retrieval;
4. Graphiti provides semantic and temporal discovery context; and
5. OpenWiki provides secondary navigation.

A graph record proves what was ingested, not that the current checkout still
implements it. Verify consequential answers against the cited local source or
tests. Label unverified and contradictory claims.

## Non-negotiable constraints

1. Read `AGENTS.md` and applicable nested instructions first.
2. Use only read-only Neo4j and Graphiti/memory operations. Reject any proposed
   `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`, ingestion,
   episode-add, or memory-write operation.
3. Confirm the Neo4j MCP targets the intended exact-graph database. Do not run
   these checks against an unknown or production database.
4. Never print credentials, connection strings containing credentials,
   tokens, raw environment values, personal data, or production content.
5. Use parameters for user-supplied paths and terms. Apply a fixed result limit.
6. Do not dump full node bodies or the full graph. Return counts, stable IDs,
   paths, headings, relationship summaries, and bounded excerpts only.
7. Do not inspect or depend on Graphiti's internal Neo4j schema. Test Graphiti
   through its supported search operation or `tools.spec_brain query`.
8. A missing required service, empty primary context, malformed provenance,
   duplicate stable ID, unsupported relationship, or context-budget breach is
   a failure, not a warning.

## Phase 1: bind the test target

Record:

- selected profile and exact database name;
- Graphiti database and group ID when selected;
- repository branch, `HEAD`, and worktree status;
- target path, questions, result limit, and observation time; and
- expected corpus scope and manifest hash when supplied.

Confirm the target path exists locally. Confirm the connected Neo4j MCP is
read-only. For the Graphiti profile, also confirm a read-only Graphiti/memory
search tool is connected or that the existing Spec Brain CLI has been
preconfigured.

## Phase 2: exact Neo4j structural checks

Run the following Cypher through the read-only Neo4j MCP. Supply parameters
separately when a query uses them.

### Check E1: exact graph root

```cypher
MATCH (repository:KB_Repository {stable_id: $repository_id})
RETURN count(repository) AS repository_roots
```

Bind `$repository_id` to `<PROJECT_ID>:repository`.

Pass only when `repository_roots = 1`.

### Check E2: label population and stable IDs

```cypher
MATCH (node)
WHERE any(label IN labels(node) WHERE label STARTS WITH 'KB_')
UNWIND labels(node) AS label
WITH label, node
WHERE label STARTS WITH 'KB_'
RETURN label,
       count(node) AS nodes,
       count(node.stable_id) AS nodes_with_stable_id,
       count(DISTINCT node.stable_id) AS distinct_stable_ids
ORDER BY label
```

Every returned label must have `nodes > 0`,
`nodes = nodes_with_stable_id`, and
`nodes = distinct_stable_ids`. Require at least `KB_Repository`,
`KB_Artifact`, `KB_Section`, and `KB_Folder`. For a full corpus, also
expect `KB_WikiPage`, `KB_SourceFile`, and `KB_TestFile`.

### Check E3: global stable-ID collisions

```cypher
MATCH (node)
WHERE any(label IN labels(node) WHERE label STARTS WITH 'KB_')
WITH node.stable_id AS stable_id, count(node) AS copies
WHERE stable_id IS NULL OR copies > 1
RETURN stable_id, copies
ORDER BY copies DESC
LIMIT $limit
```

Pass only when this query returns no rows.

### Check E4: relationship types and identifiers

```cypher
MATCH (source)-[relationship]->(target)
WHERE any(label IN labels(source) WHERE label STARTS WITH 'KB_')
  AND any(label IN labels(target) WHERE label STARTS WITH 'KB_')
RETURN type(relationship) AS relationship_type,
       count(relationship) AS relationships,
       count(relationship.stable_id) AS relationships_with_stable_id,
       count(DISTINCT relationship.stable_id) AS distinct_stable_ids
ORDER BY relationship_type
```

Every type must be one of:

`CONTAINS`, `HAS_SECTION`, `HAS_SPEC`, `PARENT_OF`, `DEPENDS_ON`,
`CONSUMED_BY`, `ASSERTS`, `EVIDENCED_BY`, `LOCATED_IN`, `DESCRIBES`,
`IMPLEMENTED_BY`, `VERIFIED_BY`, `PARTICIPATES_IN`, or `HAS_QUESTION`.

For every row, require:

- `relationships > 0`;
- `relationships = relationships_with_stable_id`; and
- `relationships = distinct_stable_ids`.

### Check E5: provenance distribution

```cypher
MATCH (section:KB_Section)
RETURN section.documentation_priority AS priority,
       count(section) AS sections,
       count(DISTINCT section.relative_path) AS source_documents
ORDER BY priority
```

Require non-empty `primary` context. Require `secondary` context when
OpenWiki was included. Any null or unsupported priority is a failure.

### Check E6: expected knowledge anchors

```cypher
MATCH (artifact:KB_Artifact)
WHERE artifact.relative_path IN [
  'knowledge-base/HLD.md',
  'knowledge-base/LLD.md',
  'knowledge-base/SPECS-RELATIONSHIP-MAP.md'
]
RETURN artifact.relative_path AS path,
       artifact.review_status AS review_status,
       artifact.content_hash AS content_hash
ORDER BY path
```

For a full corpus, require all three paths and non-empty content hashes. Report
their review status without converting draft content into reviewed truth.

## Phase 3: exact retrieval checks

Use `$target_path`, `$terms`, and `$limit` as separately bound parameters.
Derive a small set of lowercase search terms from `QUESTION`; exclude generic
words such as `change`, `design`, `feature`, and `requirements`.

### Check R1: bounded primary retrieval

```cypher
MATCH (section:KB_Section)
WHERE section.documentation_priority = 'primary'
WITH section,
     size([
       term IN $terms
       WHERE toLower(coalesce(section.body, '')) CONTAINS term
          OR toLower(coalesce(section.name, '')) CONTAINS term
     ]) AS score,
     section.relative_path = $target_path
       OR section.relative_path STARTS WITH $target_path + '/'
       OR any(path IN coalesce(section.mentioned_paths, [])
              WHERE path = $target_path
                 OR path STARTS WITH $target_path + '/') AS path_match
WHERE score > 0 OR path_match
RETURN section.stable_id AS stable_id,
       section.relative_path AS path,
       section.heading_path AS heading,
       section.mentioned_paths AS source_paths,
       section.mentioned_tests AS test_paths,
       score,
       path_match
ORDER BY path_match DESC, score DESC, path, stable_id
LIMIT $limit
```

Require at least one primary result. Every result must have a stable ID, path,
and heading.

### Check R2: owning folder and impact neighborhood

```cypher
MATCH (folder:KB_Folder)
WHERE $target_path = folder.relative_path
   OR $target_path STARTS WITH folder.relative_path + '/'
WITH folder
ORDER BY size(folder.relative_path) DESC
LIMIT 1
OPTIONAL MATCH (folder)-[:DEPENDS_ON|PARENT_OF*1..2]-(related:KB_Folder)
RETURN folder.stable_id AS owner_id,
       folder.relative_path AS owner_path,
       [item IN collect(DISTINCT related)
        WHERE item IS NOT NULL |
        {stable_id: item.stable_id, path: item.relative_path}
       ][0..$limit] AS related_folders
```

Require one owning folder. Report an empty neighborhood as a warning unless the
selected target is expected to be isolated.

### Check R3: local evidence verification

From R1, deduplicate the returned source and test paths. Verify that each path
stays inside the repository and exists. Inspect a maximum of `MAX_RESULTS`
files, prioritizing paths cited by the highest-scoring primary records.

Select at least one material retrieved claim and classify it as:

- `VERIFIED`: current source or a focused test supports it;
- `CONTRADICTED`: current source or test disagrees; or
- `UNVERIFIED`: the cited path is missing or insufficient.

The exact profile passes only when primary retrieval succeeds, paths are safe,
and at least one material claim is verified. A contradiction is always
reported, even when the remaining checks pass.

## Phase 4: Graphiti checks

Skip this phase only for `PROFILE: neo4j`.

For `PROFILE: neo4j-graphiti`, prefer the connected read-only Graphiti or
memory MCP search tool, following the installed `spec-brain` skill. Search
both `QUESTION` and `PARAPHRASE` in the configured group. Do not create
episodes or memories.

If the MCP search transport is unavailable, use the preconfigured CLI:

```powershell
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain check-config --component query
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain check-services
uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain query --request "<QUESTION>" --target-path <TARGET_PATH> --mode all --format json --output <CONTEXT_OUTPUT>
```

Create a second temporary context output and repeat `query` with
`PARAPHRASE`.

### Check G1: semantic result structure

Require at least one bounded semantic result for one of the two equivalent
questions. Each accepted semantic fact must contain:

- a non-empty stable identifier and fact;
- source and target entity context when supplied;
- at least one source episode;
- valid/invalid time fields when supplied.

Missing optional time fields are not a failure. Missing fact text, identity,
or episode provenance is a failure. Separately require evidence that the search
operation was restricted to the configured Graphiti group.

### Check G2: combined context contract

For each Spec Brain context package, require:

- non-empty `primary_context`;
- non-empty `exact_module_relationships` when the target has known
  relationships;
- bounded `semantic_context`;
- `source_and_test_locations`;
- `secondary_context` after primary context;
- `estimated_tokens <= max_context_tokens`; and
- `implementation_authorized = false` under `suggested_spec_scope`.

### Check G3: paraphrase stability

The two queries need not return identical semantic rankings. They must share at
least one primary stable ID, exact folder relationship, or verified source/test
path. If they have no shared exact anchor, mark semantic retrieval unstable.

### Check G4: semantic corroboration

Select the highest-relevance Graphiti fact that affects the answer. Verify it
against an exact node relationship and current source or focused tests.
Graphiti-only support is `UNVERIFIED`, never `VERIFIED`.

The Graphiti profile fails when semantic retrieval is unavailable, provenance
is missing, the context exceeds its budget, the two paraphrases have no shared
exact anchor, or no semantic fact can be corroborated.

## Result matrix

Report every check in a table:

| ID | Profile | Status | Evidence | Observed | Expected | Action |
| --- | --- | --- | --- | --- | --- | --- |
| E1-E6 | both | PASS/WARN/FAIL | query and bounded result | value | invariant | next step |
| R1-R3 | both | PASS/WARN/FAIL | stable IDs and local paths | value | invariant | next step |
| G1-G4 | Graphiti | PASS/WARN/FAIL/SKIP | semantic/context evidence | value | invariant | next step |

Use these overall results:

- `PASS`: every required check for the selected profile passed and no
  material contradiction remains.
- `WARN`: all critical checks passed, with only bounded coverage or
  review-status warnings.
- `FAIL`: any required invariant, retrieval, provenance, service, budget, or
  corroboration check failed.
- `BLOCKED`: the exact target, database, required read-only tool, or local
  repository evidence could not be established.

End with:

- selected profile and database/group;
- exact graph counts by label and relationship type;
- the two questions and shared retrieval anchors;
- verified, contradicted, and unverified claims;
- missing/stale knowledge and broken path evidence;
- the smallest safe corrective action; and
- the overall status.

Do not repair or repopulate the graph during this sanity test.

