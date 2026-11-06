---
name: spec-brain
description: Retrieve exact Neo4j relationships and Graphiti semantic context through the workspace MCP servers before creating or updating Kiro requirements, design, tasks, impact analysis, or specifications.
---

# Specification Brain

Use this skill for specification authoring, change-impact analysis, and
requirements, design, or task updates that need repository context.

## Workspace graph transports

Use the workspace servers in this order:

1. Use the neo4j MCP server for deterministic KB_* nodes and relationships.
   Run only its read-only schema and Cypher query tools.
2. Use the graphiti MCP server for semantic and temporal memory. Start with
   spec_brain_graphiti_status, then use spec_brain_search_graphiti or
   spec_brain_build_context.
3. Treat the generic memory MCP as unrelated unless it explicitly identifies
   itself as the configured Graphiti group-aware server.

The graphiti server is valid only when it reports:

- read_only = true;
- mutation_tools_exposed = false;
- the expected Neo4j and Graphiti databases;
- the configured group ID; and
- semantic_configured = true for fact search or query_configured = true for a
  combined context package.

Do not infer Graphiti availability from Entity, Episodic, or RELATES_TO labels
returned by the neo4j MCP. A successful group-scoped Graphiti search is the
proof that semantic retrieval is active.

## Required workflow

1. Preserve the user's request verbatim. Record explicit target folders, files,
   interfaces, and models without broadening the request.
2. Query the neo4j MCP for the narrowest exact context:
   - the current `KB_Service`, its `KB_KnowledgePlane`, and declared service,
     interface, and event relationships;
   - primary KB_Section records matching the request and target paths;
   - owning KB_Folder nodes;
   - bounded PARENT_OF and DEPENDS_ON relationships;
   - affected KB_FolderSpec records; and
   - linked KB_SourceFile and KB_TestFile locations.
3. Call spec_brain_graphiti_status. Stop if the server is not read-only, the
   target database or group is unexpected, or semantic configuration is
   incomplete.
4. For ordinary semantic discovery, call spec_brain_search_graphiti with the
   complete request. Accept facts only from the group ID reported by status.
5. For requirements, design, tasks, or impact analysis, prefer
   spec_brain_build_context with the complete request, every explicit target
   path, the requested mode, and a bounded result count. Read its context in
   this order:
   - primary_context;
   - exact_service_relationships;
   - exact_module_relationships;
   - source_and_test_locations;
   - semantic_context;
   - secondary_context.
6. When exact service relationships implicate another repository, inspect its
   primary contract context and cited interface or event schema before changing
   the current service. Keep target-path matching scoped to the active project.
7. Verify material semantic facts against exact KB_* records and current source
   or focused tests. Graphiti similarity alone never establishes implemented
   behavior.
8. When material ambiguity remains, inspect the precise source or test paths
   returned by the graph tools. Keep contradictions and unresolved questions
   visible.
9. Create requested specifications using
   prompt/kiro-spec-template-knowledge-primary-openwiki-secondary.md.
10. Do not implement a change until the user separately requests implementation.

## CLI fallback

Use the local CLI only when the workspace graphiti MCP server is unavailable
and its environment was configured before the task. Confirm
the packaged `.aide/full/spec-brain` runtime exists, then run:

    uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain check-config --component query
    uv run --project .aide/full/spec-brain --offline --frozen aide-spec-brain check-services

Stop when either command fails. For a valid fallback, query once with the full
request, every explicit target path, the requested mode, JSON format, and a
temporary output path. Do not install dependencies, add credentials, start
services, or silently continue without Graphiti.

## Output emphasis

For requirements.md, cover user intent, supported and unsupported scenarios,
observable inputs and outputs, functional and non-functional requirements,
compatibility constraints, acceptance criteria, affected interfaces, and open
decisions.

For design.md, cover current architecture, proposed responsibilities, contracts
and models, sequence and data flows, exceptions and cleanup, configuration,
resource ownership, affected modules, and alternatives.

For tasks.md, include specification updates, focused tests, the smallest ordered
implementation steps, affected source and test paths, manual validation, and
final reconciliation. Trace each task to a requirement, design decision,
invariant, or reproduced defect.

## Boundaries

- knowledge-base/, its reviewed knowledge-plane descriptor, and folder
  SPECS.md files are primary design context.
- Accept cross-service links only from exact plane-scoped relationships or
  verified contracts. Graphiti similarity can identify candidates.
- Exact Neo4j relationships and repository source or tests outweigh semantic
  similarity.
- OpenWiki is secondary context and cannot establish a requirement alone.
- Machine-generated graph facts and specifications remain drafts until review.
- Never expose credentials, tokens, or credential-bearing connection strings.
- Never send repository content to an unapproved endpoint.
- Never modify OpenWiki claim sidecars through this workflow.
- Never call graph create, merge, set, delete, clear, ingestion, episode-add,
  or memory-write operations.
- A Graphiti retrieval, provenance, group-boundary, or context-budget failure
  is a safe stop.

