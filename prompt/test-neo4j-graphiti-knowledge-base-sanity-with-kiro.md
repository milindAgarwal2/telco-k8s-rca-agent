# Kiro Prompt: Test Neo4j + Graphiti Knowledge-Base Sanity

Copy the prompt below into Kiro after the exact Neo4j graph and Graphiti
episodes have been populated. Replace the sample values, but keep
PROFILE: neo4j-graphiti and GRAPHITI_REQUIRED: true unchanged.

---

You are working in the current repository. Perform a read-only sanity test of
the Neo4j exact knowledge graph and its Graphiti semantic and temporal memory.
Graphiti is mandatory in this test. Do not skip its checks, silently use a
Neo4j-only profile, or report success when Graphiti is unavailable.

## Input block

```text
PROFILE: neo4j-graphiti
GRAPHITI_REQUIRED: true
GRAPHITI_TRANSPORT: workspace-mcp
PROJECT_ID: <configured or repository-derived project ID>
TARGET_PATH: <repository-relative component path>
QUESTION: <concrete architecture or behavior question>
PARAPHRASE: <semantically equivalent wording of QUESTION>
MAX_RESULTS: 20
EXPECTED_CORPUS_SCOPE: full
EXPECTED_MANIFEST_SHA256: <optional hash from the ingestion report>
QUESTION_CONTEXT_OUTPUT: <temporary JSON output path>
PARAPHRASE_CONTEXT_OUTPUT: <different temporary JSON output path>
```

Reject the request if PROFILE is not exactly neo4j-graphiti,
GRAPHITI_REQUIRED is not exactly true, or GRAPHITI_TRANSPORT is not exactly
workspace-mcp. Require a repository-relative
TARGET_PATH, a Graphiti-safe PROJECT_ID, a concrete QUESTION, a semantically
equivalent PARAPHRASE,
two distinct temporary output paths, and MAX_RESULTS from 1 through 50.

## Evidence and safety rules

1. Read AGENTS.md, applicable nested instructions, and the installed
   .kiro/skills/spec-brain/SKILL.md first.
2. Treat current source, schemas, configuration, build definitions, and
   focused tests as implemented truth. Use reviewed knowledge-base/ and
   folder SPECS.md files as primary design context, exact Neo4j KB_*
   records as deterministic retrieval, Graphiti as semantic and temporal
   discovery context, and OpenWiki as secondary navigation.
3. Use only read-only Neo4j and Graphiti or memory operations. Reject
   CREATE, MERGE, SET, DELETE, REMOVE, DROP, ingestion,
   load-graphiti, episode-add, and memory-write operations.
4. Confirm the exact Neo4j database, Graphiti database, and Graphiti group ID.
   Stop when any target is unknown or appears to be a production database.
5. Never expose credentials, credential-bearing connection strings, tokens,
   raw environment values, personal data, or production content.
6. Use parameters for user-supplied values and fixed result limits. Return
   stable IDs, paths, headings, relationship summaries, and bounded excerpts;
   do not dump full node bodies, episodes, or graphs.
7. Test Graphiti only through the workspace `graphiti` MCP server's read-only
   status, search, and combined-context operations. Never inspect or depend on
   Graphiti's internal Neo4j schema.
8. A Graphiti skip, empty semantic result, missing provenance, missing group
   boundary, failed service, silent downgrade, context-budget breach, or
   uncorroborated semantic fact is FAIL or BLOCKED, never WARN or PASS.

## Phase 1: bind targets and prove Graphiti is enabled

Record the repository branch, HEAD, worktree status, target path, questions,
result limit, observation time, corpus scope, and expected manifest hash when
supplied. Confirm TARGET_PATH exists inside the repository.

The first MCP call in this test must be exactly
`@graphiti/spec_brain_graphiti_status`. Do not call `memory`, Neo4j, a shell,
or the Spec Brain CLI before that status call. Record the exact Neo4j database
name and the status tool's configured Graphiti database and group ID without
revealing secrets.

Require the workspace `graphiti` MCP server to expose
`spec_brain_graphiti_status`, `spec_brain_search_graphiti`, and
`spec_brain_build_context`. If the server or status tool is absent, report
`BLOCKED: workspace graphiti MCP is not registered` and stop immediately.
Do not probe generic `memory`, inspect Graphiti's internal Neo4j schema, or use
the CLI as a fallback in this dedicated MCP test.

After status succeeds, call `@graphiti/spec_brain_graphiti_health`. It must
confirm the exact Neo4j service, approved language-model service, approved
embedding service, database, and group boundary. If status reports incomplete
configuration or health fails, report the redacted failure and stop. Do not
install packages, start services, configure credentials, or log in
interactively.

## Phase 2: establish exact Neo4j anchors

Run the following parameterized, bounded Cypher with the read-only Neo4j MCP.

### Check E1: repository root

```cypher
MATCH (repository:KB_Repository {stable_id: $repository_id})
RETURN count(repository) AS repository_roots
```

Bind `$repository_id` to `<PROJECT_ID>:repository`.

Pass only when repository_roots = 1.

### Check E2: unique stable identifiers

```cypher
MATCH (node)
WHERE any(label IN labels(node) WHERE label STARTS WITH 'KB_')
WITH node.stable_id AS stable_id, count(node) AS copies
WHERE stable_id IS NULL OR copies > 1
RETURN stable_id, copies
ORDER BY copies DESC
LIMIT $limit
```

Pass only when no rows are returned.

### Check E3: bounded primary target context

Derive a small set of lowercase search terms from QUESTION, excluding
generic words such as change, design, feature, and requirements.
Bind $target_path, $terms, and $limit separately.

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
and heading. Preserve these results as the exact anchors used by the Graphiti
checks.

### Check E4: owning folder and exact relationships

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

Require one owning folder. Preserve its stable ID, path, and bounded exact
relationships for paraphrase comparison and semantic corroboration.

## Phase 3: query Graphiti twice

Search the configured Graphiti group with the complete QUESTION, target
path, and result limit. Repeat with PARAPHRASE. The two searches must use the
same database, group ID, target path, limit, and context budget. Do not create
episodes or memories.

Call `@graphiti/spec_brain_build_context` once with QUESTION and once with
PARAPHRASE, using the same TARGET_PATH, mode `all`, and MAX_RESULTS. Compose
and evaluate the returned bounded context fields locally. Do not create
temporary output files or invoke the Spec Brain CLI.

## Phase 4: mandatory Graphiti checks

### Check G1: semantic retrieval is active

Require non-empty, bounded semantic_context for both questions. Show the
semantic result count for each query and enough bounded metadata to prove the
results came from Graphiti. Exact Neo4j results alone do not satisfy this
check.

### Check G2: group isolation

Require explicit evidence that both searches were restricted to the same
configured Graphiti group ID. A group inferred only from result text is
insufficient. Fail if the search tool cannot prove the group boundary.

### Check G3: fact identity and provenance

Every accepted semantic fact must have:

- a non-empty stable identifier and fact text;
- at least one source episode;
- source and target entity context when supplied; and
- valid and invalid time fields when supplied.

Missing optional time fields is acceptable. Missing identity, fact text, or
episode provenance is a failure. Report only bounded excerpts.

### Check G4: combined context contract

For both context packages, require:

- non-empty primary_context before semantic and secondary context;
- the owning folder and exact module relationships when present;
- non-empty, bounded semantic_context;
- source_and_test_locations;
- secondary_context after primary context;
- estimated_tokens <= max_context_tokens; and
- implementation_authorized = false under suggested_spec_scope.

### Check G5: paraphrase stability

The semantic rankings may differ, but the two queries must share at least one
meaningful anchor: a Graphiti fact stable ID, primary context stable ID, exact
folder relationship, or verified source/test path. Report the shared anchors
and the top unique results for each query. Fail if no meaningful anchor is
shared.

### Check G6: semantic corroboration

Select the highest-relevance material Graphiti fact from each query. For each
fact:

1. find the related exact KB_* node or relationship;
2. follow its bounded source or test paths;
3. confirm every path stays inside the repository and exists; and
4. inspect current source or a focused test.

Classify each fact as:

- VERIFIED: both an exact graph anchor and current source or test support it;
- CONTRADICTED: current source or test disagrees; or
- UNVERIFIED: exact or local evidence is missing or insufficient.

Graphiti-only support is always UNVERIFIED. Require at least one material
Graphiti fact to be VERIFIED. Always report contradictions.

### Check G7: temporal sanity

For results carrying validity timestamps, verify that their ordering is
coherent and explain which fact is current at the observation time. Report
superseded or conflicting facts. If the bounded result set contains no
temporal fields, report WARN; do not invent timestamps.

## Result contract

Report every check in this table:

| ID | Status | Evidence | Observed | Expected | Action |
| --- | --- | --- | --- | --- | --- |
| E1-E4 | PASS/WARN/FAIL/BLOCKED | bounded exact evidence | value | invariant | next step |
| G1-G7 | PASS/WARN/FAIL/BLOCKED | bounded Graphiti/context evidence | value | invariant | next step |

SKIP is not an allowed status. Use these overall results:

- PASS: all exact and Graphiti checks pass, at least one material semantic
  fact is verified, and no material contradiction remains.
- WARN: all required checks pass, with only bounded coverage, draft-review,
  or absent optional temporal-field warnings.
- FAIL: a required exact or Graphiti invariant fails.
- BLOCKED: the intended databases, configured Graphiti group, required
  read-only transport, or local evidence cannot be established.

End with:

- Graphiti execution: CONFIRMED or Graphiti execution: NOT CONFIRMED;
- exact Neo4j database, Graphiti database, and group ID;
- service and query transport used;
- the two questions and their shared anchors;
- verified, contradicted, and unverified semantic facts;
- temporal findings;
- missing or stale knowledge and broken path evidence;
- the smallest safe corrective action; and
- the overall status.

Do not repair, repopulate, or mutate either graph during this test.
