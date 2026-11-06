# Kiro Prompt: Generate the Complete Folder-Specification Relationship Map

Copy the prompt below into Kiro while the repository root is the active
workspace.

---

You are working in the current repository. Create or refresh a comprehensive,
source-linked relationship map for every project-owned `SPECS.md` folder
specification and write it to:

`knowledge-base/SPECS-RELATIONSHIP-MAP.md`

Also reconcile `knowledge-base/SPECS.md` with the final artifact so its direct
file count, direct artifact size, content summary, and evidence inventory remain
accurate.

## Objective

Build a single Markdown navigation and impact-analysis artifact that includes
every in-scope folder specification exactly once and records every structural
and declared cross-folder relationship that can be extracted from the
specification hierarchy.

The relationship map must enable an engineer to:

- find any folder specification from one master catalog;
- identify its structural parent and immediate structural children;
- identify specifications it directly depends on;
- identify specifications that directly consume it;
- understand which dependency edges were declared outbound, inbound, or from
  both endpoint perspectives;
- see high-level repository areas and cross-area dependency concentrations;
- find structural aggregators, dependency hubs, leaves, and isolated nodes;
- estimate the specification impact radius before changing a contract;
- distinguish physical hierarchy from bounded static dependency evidence;
- locate relationship gaps that require maintainer review.

This is a relationship map of the existing specifications. It must not become
a proposed architecture, a modernization plan, or an invented runtime graph.

## Required deliverables

1. Create or update
   `knowledge-base/SPECS-RELATIONSHIP-MAP.md`.
2. Update `knowledge-base/SPECS.md` only as needed to include the relationship
   map in that folder's contract and evidence inventory.
3. Do not create any other persistent artifact.
4. If temporary local generation or validation tooling is necessary, remove it
   before completion.

## Non-negotiable constraints

1. Read and obey the repository's `AGENTS.md` and all applicable nested or
   domain-specific instructions before working.
2. Treat source code, tests, schemas, build definitions, and maintained
   configuration as authoritative if a folder specification conflicts with
   repository evidence.
3. Use the existing project-owned `SPECS.md` files as the primary relationship
   input. Do not regenerate the folder specifications as part of this task.
4. Do not use generated OpenWiki pages as evidence or context. Do not run
   OpenWiki and do not modify `openwiki/`, especially `openwiki/.claims/`.
5. Do not modify application source, tests, build definitions, configuration,
   workflows, diagrams, generated artifacts, prompts, or unrelated
   documentation.
6. Preserve every unrelated and pre-existing workspace change. Never reset,
   revert, delete, format, or overwrite it.
7. Do not start servers, run model inference, download models, install
   dependencies, run expensive test suites, or invoke external documentation
   generators.
8. Do not send repository content to an unapproved external provider. Work
   entirely in the approved workspace.
9. Never invent a specification node, dependency, consumer, parent, child,
   runtime call, interface, model, environment variable, or deployment flow.
10. Do not infer a runtime call merely because one specification links to
    another. Preserve the declared relationship semantics.
11. Clearly label bounded-scan limitations, one-sided declarations, dynamic
    relationships, deployment-specific behavior, and unresolved findings.
12. Do not reproduce secrets, credentials, personal data, production records,
    proprietary payloads, or large source-code blocks.
13. Mark the map as a draft until maintainers review it.
14. Use simple, precise English and exact repository-relative paths.

## Checkpointed execution and AIDE overlay boundary

This prompt is run by an automated, resumable post-installation workflow.
Complete the safe work without asking the operator to select a scope or
preservation strategy. Ask a question only when a credential, authorization,
missing external input, or destructive action makes safe progress impossible.

Before collecting candidate specifications, check for
`.aide/managed-files.json`. When it exists, parse its top-level `files`,
`control_files`, and `settings` path keys and exclude those exact managed paths.
Always exclude `.aide/`, `.kiro/`, and `openwiki/` from the relationship graph.
Their installed `SPECS.md` files document the AIDE support plane, not the target
application, and must not affect node counts, hierarchy checks, dependency
metrics, or the final map. Preserve all excluded files unchanged.

## Establish the exact specification scope

Discover the scope dynamically. Do not hard-code a specification count from a
previous run.

### Include

Include:

- the root `SPECS.md`;
- every project-owned subfolder `SPECS.md` represented by tracked or
  non-ignored workspace content;
- specifications under source, tests, native code, build, packaging,
  deployment, workflows, documentation, examples, benchmarks, fixtures,
  configuration, prompts, skills, policies, diagrams, and artifacts;
- hidden project-owned directories when they are part of repository content.

### Exclude

Exclude:

- `.git/` and other version-control internals;
- AIDE-managed paths identified by `.aide/managed-files.json`;
- `.aide/`, `.kiro/`, `openwiki/`, and their generated or support content;
- ignored dependency installations, virtual environments, caches, coverage
  output, logs, core dumps, editor state, temporary directories, downloaded
  models, and transient build output;
- `SPECS.md` files found inside nested or vendored repositories that are not
  maintained as part of this repository.

### Scope checks

Before writing:

1. inventory all candidate `SPECS.md` files recursively, including hidden
   project directories;
2. resolve every path to an absolute canonical path;
3. remove excluded boundaries;
4. map each specification to its repository-relative folder;
5. verify exactly one root specification exists;
6. verify every non-root specification's nearest physical parent folder has a
   specification;
7. verify specification identifiers and roles can be parsed from metadata;
8. record total, root, subfolder, and top-level-area counts.

Stop safely and report the exact malformed or disconnected paths if the
specification set cannot be made into one rooted hierarchy without inventing
nodes.

## Relationship model

Keep structural and dependency relationships separate.

### 1. Structural hierarchy

The structural hierarchy is authoritative for folder containment:

- each directory containing `SPECS.md` is one node;
- the repository root is the single root node;
- every non-root node has exactly one parent;
- the parent is derived from the physical repository-relative directory path;
- an immediate child is the reverse of that parent edge;
- the expected structural-edge count is node count minus one.

Do not rely only on section-6 `Parent` or `Child` rows to build the hierarchy.
Those rows are generated relationship evidence and may be bounded. Compare
them with the physical hierarchy and report discrepancies.

### 2. Declared dependency relationships

Parse section `## 6. Interaction points` from every specification. Recognize
the standard table rows:

- `Parent`;
- `Child`;
- `Outbound`;
- `Inbound`.

Use `Outbound` and `Inbound` rows to create the normalized dependency graph:

- an `Outbound` declaration in specification A targeting specification B
  becomes the edge A → B;
- an `Inbound` declaration in specification B naming consumer A is reversed
  into the same normalized edge A → B;
- identical normalized source/target pairs are deduplicated;
- keep a set of declaration perspectives for each edge;
- keep a link to every specification whose section 6 supplied evidence;
- label an edge `Outbound only`, `Inbound only`, or `Both perspectives`;
- retain self-reference edges but count and label them explicitly;
- resolve all target links relative to the declaring specification's folder.

Do not discard one-sided edges. A one-sided declaration is not automatically a
defect because inbound scans can be capped and dynamic relationships may not be
visible to the same static heuristic.

### 3. Evidence semantics

Apply these rules consistently:

- physical placement proves folder containment;
- a valid relative link proves the declared specification target exists;
- an outbound row proves the declaring specification records a dependency;
- an inbound row proves the target specification records a consumer;
- matching outbound and inbound rows provide two declaration perspectives;
- a dependency declaration does not prove a particular function call,
  execution order, data format, or deployment topology;
- absence from the map means “not declared by the parsed specification set,”
  not “cannot exist at runtime.”

## Extraction workflow

### A. Parse node metadata

For every specification, extract:

- specification identifier;
- repository-relative folder;
- role;
- evidence baseline;
- status;
- parent-specification link;
- direct-file count when present;
- section-6 interaction rows.

Create stable internal node keys from canonical repository-relative folder
paths. Do not use display labels as identity when two labels could collide.

### B. Derive structural edges

For every non-root node:

1. derive the parent folder from its repository-relative path;
2. resolve the parent specification;
3. create exactly one parent → child edge;
4. increment the parent's child count;
5. calculate node depth and top-level area.

Verify that the resulting graph is connected, acyclic, rooted, and contains
every node exactly once.

### C. Normalize dependency edges

For each `Outbound` or `Inbound` relationship row:

1. resolve the Markdown link relative to the declaring specification;
2. verify the target is an in-scope `SPECS.md` file;
3. orient the edge according to the rules above;
4. use the canonical source/target folder pair as the deduplication key;
5. retain declaration kind and declaring specification as evidence;
6. count malformed rows and unresolved targets;
7. never silently omit an unparseable relationship row.

### D. Calculate navigation and impact metrics

For each node, calculate:

- structural parent;
- immediate child count;
- depth;
- top-level area;
- normalized outbound degree;
- normalized inbound degree;
- total dependency degree;
- leaf status;
- dependency-isolated status.

Calculate repository totals for:

- nodes;
- root and non-root nodes;
- structural edges;
- normalized dependency edges;
- declared Parent, Child, Outbound, and Inbound rows;
- edges declared from both perspectives;
- outbound-only edges;
- inbound-only edges;
- self-reference edges;
- structural leaves;
- dependency-isolated nodes;
- maximum hierarchy depth;
- malformed rows and unresolved targets.

### E. Aggregate top-level relationships

Group nodes by their first repository-relative path segment. For every area,
calculate:

- specification count;
- structural leaf count;
- normalized outbound dependency count;
- normalized inbound dependency count.

Aggregate normalized dependency edges by source and target top-level areas.
Retain same-area edges and cross-area edges. Sort the rollup by descending edge
count and then deterministic area names.

## Required document structure

Write `knowledge-base/SPECS-RELATIONSHIP-MAP.md` with the following sections.

### Title and document control

Use the title:

`# Repository Folder Specification Relationship Map`

Provide:

- artifact path;
- current commit plus workspace-specification baseline;
- generation date;
- node count;
- structural-edge count;
- normalized dependency-edge count;
- draft/review status;
- authority and static-analysis caveats.

### 1. Purpose and scope

Explain how the map supports navigation, contract impact analysis, hub/leaf
discovery, relationship review, and spec-driven development. State included and
excluded boundaries.

### 2. Relationship semantics

Provide a table that defines structural parent, structural child, outbound
dependency, inbound consumer, normalized orientation, deduplication, and
evidence perspectives.

### 3. Repository-level hierarchy diagram

Include one renderable Mermaid diagram containing the repository root and every
top-level project area with specification counts. Do not put hundreds of nodes
into one Mermaid diagram. The complete hierarchy belongs in linked lists and
tables.

### 4. Top-level area summary

Provide one row per top-level area with specification, leaf, outbound, and
inbound counts. Link area names to their specifications.

### 5. Cross-area dependency rollup

Provide every non-zero top-level source/target pair and unique normalized edge
count. Include same-area rows.

### 6. Dependency and hierarchy hubs

Provide at least:

- the 30 highest dependency-degree specifications;
- the 30 largest structural aggregators;
- outbound, inbound, total degree, and child counts;
- relative links to every listed specification.

### 7. Complete specification hierarchy

Create a deterministic nested Markdown list containing every specification
exactly once. Indentation must represent physical folder depth. Each entry must
include:

- folder path;
- link to `SPECS.md`;
- specification identifier;
- role.

### 8. Complete specification node catalog

Provide exactly one row per node with:

- ordinal;
- linked folder specification;
- specification identifier;
- role;
- linked structural parent or root marker;
- immediate child count;
- direct-file count when available;
- normalized outbound degree;
- normalized inbound degree.

### 9. Complete structural edge catalog

Provide exactly one row per non-root node with linked parent and child
specifications. Row count must equal node count minus one.

### 10. Complete normalized dependency edge catalog

Provide exactly one row per unique normalized dependency edge with:

- ordinal;
- linked source specification;
- linked target specification;
- declaration perspective or perspectives;
- links to all specifications that declared the relationship.

Do not cap or sample this catalog. “Complete” means every parsed, resolved,
deduplicated edge.

### 11. Integrity observations

Report leaves, isolated nodes, self-reference edges, maximum depth, and the
three declaration-perspective categories. Explain why one-sided declarations
are review signals rather than automatic defects.

### 12. Generation and validation record

Record all parsing and relationship totals, including malformed rows and
unresolved targets. Explain any difference between declared Child rows and
physical structural edges.

### 13. Spec-driven impact-analysis procedure

Provide a concise procedure for using structural parents/children, outbound
targets, and inbound consumers before changing a folder contract. Require
affected specifications and verification evidence to be updated with the
change.

### 14. Unknowns and review items

Record dynamic or deployment-only relationships, one-sided edges needing
review, maintainer ownership questions, and map-refresh triggers. Do not add
unsolicited modernization recommendations.

## Link and formatting requirements

1. Use relative Markdown links resolved from the `knowledge-base/` folder.
2. Link every specification occurrence in the hierarchy, catalogs, summaries,
   and evidence fields.
3. Use angle-bracket Markdown destinations when needed for path safety.
4. Escape table-cell delimiters and normalize embedded newlines.
5. Sort nodes by repository-relative path, with the root first.
6. Sort structural edges by child path.
7. Sort normalized dependency edges by source path and then target path.
8. Keep table headers and column counts consistent.
9. Keep diagrams small enough to render.
10. Do not reproduce source-code blocks.

## Safe generation procedure

1. Record the current commit, date, repository status, and existing map state.
2. Inventory and parse the full specification set without writing.
3. Fail safely if identifiers, roles, hierarchy parents, or relationship
   targets cannot be resolved.
4. Build node and edge models in memory.
5. Generate the map deterministically.
6. Reconcile `knowledge-base/SPECS.md` with the completed artifact, preserving
   maintainer-authored constraints and review notes.
7. If updating the folder specification changes data included in the map,
   regenerate the map once from the final specification state.
8. Remove temporary tooling.
9. Run all validation gates below.
10. Preserve the existing map on an unrecoverable failure; do not replace it
    with an incomplete artifact.

## Mandatory validation gates

Do not report completion until all applicable checks pass.

### Node coverage

- The map's node count equals the in-scope `SPECS.md` count.
- The hierarchy contains every specification exactly once.
- The node catalog contains every specification exactly once.
- No duplicate specification identifier or canonical folder key exists.
- Exactly one root exists.
- Every non-root node resolves to one parent.
- Structural-edge count equals node count minus one.

### Relationship integrity

- Every recognized section-6 relationship row is parsed or reported.
- Every dependency target resolves to an in-scope specification.
- Normalized source/target pairs are unique.
- Every edge retains its declaration perspectives and evidence links.
- Outbound-only, inbound-only, both-perspective, and self-reference counts sum
  consistently.
- Top-level rollup totals reconcile with the dependency catalog.

### Links and Markdown

- Resolve every relative Markdown link from the map's directory.
- Broken-link count is zero.
- Every hierarchy, node, structural-edge, dependency-edge, summary, and
  evidence link targets an existing specification.
- Mermaid and other block fences are balanced.
- The Mermaid diagram parses syntactically and has one node per top-level area.
- Heading hierarchy and table column counts are valid.
- No conflict markers, unfinished template tokens, `TODO`, or `TBD` placeholders
  remain.

### Safety and workspace boundaries

- Only `knowledge-base/SPECS-RELATIONSHIP-MAP.md` and the necessary evidence
  updates to `knowledge-base/SPECS.md` were changed by the map-generation task.
- No application source, tests, build definitions, configuration, OpenWiki
  content, prompts, or unrelated documentation were modified.
- No temporary generator remains.
- No secret, credential, personal data, production payload, or large source
  block was copied.
- All pre-existing unrelated workspace changes remain untouched.

### Final metrics

Report:

- specification node count;
- root and subfolder counts;
- structural-edge count;
- normalized dependency-edge count;
- declared relationship rows by kind;
- both-perspective, outbound-only, inbound-only, and self-reference counts;
- structural leaf and dependency-isolate counts;
- maximum hierarchy depth;
- hierarchy entry count;
- node-catalog row count;
- structural-edge row count;
- dependency-edge row count;
- total relative links checked and broken-link count;
- Markdown fence and structural validation results;
- approximate line, word, and byte counts.

## Final response

Respond with the outcome first, followed by:

- a link to `knowledge-base/SPECS-RELATIONSHIP-MAP.md`;
- exact node, structural-edge, and normalized dependency-edge counts;
- confirmation that every in-scope specification appears in both the hierarchy
  and node catalog;
- declared-row parsing and unresolved-target results;
- relative-link and Markdown validation results;
- approximate artifact size;
- a concise explanation of relationship semantics and important review gaps;
- confirmation that `knowledge-base/SPECS.md` was reconciled;
- confirmation that no application source, tests, or OpenWiki content were
  modified.

Do not paste the complete relationship map into chat. The generated Markdown
file is the handoff artifact.

---

