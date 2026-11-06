# Generate a Kiro Specification from an EARS Jira Story

This prompt is used by the `aide-story-lifecycle` hook. It accepts any active
Jira story and contains no issue-specific requirements.

## Runtime input

Run:

```powershell
uv run --project .aide/full/hook --offline --frozen aide-hook aide-story-to-spec
```

Continue only when its JSON action is `generate` or `repair`. Use exactly the
returned `story_path`, `spec_dir`, `jira_key`, and `gaps`. The command owns
retry limits and path authorization.

## Evidence order

1. The EARS-ready story defines requested behavior.
2. Source, schemas, configuration, and tests define current behavior.
3. Reviewed specifications and `knowledge-base/` provide maintained design
   context.
4. Folder `SPECS.md` files and OpenWiki provide repository orientation.
5. Read-only Neo4j or Graphiti results provide relationship and historical
   leads. Verify consequential graph claims against current repository files.

Label direct evidence, graph-derived leads, inference, requested behavior, and
unknowns separately. A graph result never overrides current source or tests.

## Procedure

1. Read `AGENTS.md`, the complete `story_path`, active workflow state, and any
   existing documents in `spec_dir`. Preserve unrelated changes and metadata.
2. Follow the installed `spec-brain` skill. Prefer Kiro's connected read-only
   Neo4j and Graphiti MCP tools; use its configured CLI only as a fallback.
3. Use the read-only `aide-spec-mcp` tools when available:
   `aide_spec_status`, `aide_build_spec_context`,
   `aide_resolve_folder_specifications`, and
   `aide_build_spec_traceability`.
4. Inspect the exact current source and focused tests cited by those tools.
   Record contradictions and inaccessible evidence instead of guessing.
5. Create or update only:
   - `<spec_dir>/requirements.md`;
   - `<spec_dir>/design.md`; and
   - `<spec_dir>/tasks.md`.
6. Run `aide_assess_spec_document` for each document when available. On a
   `repair` action, fix only the returned lifecycle gaps and findings.
7. Rerun `aide-story-to-spec`. Repeat only for `repair`; stop immediately on
   `complete`, `blocked`, or `none`.

## Document contracts

`requirements.md` must trace the Jira key and story requirements, state scope
and exclusions, retain stable EARS identifiers, define observable acceptance
criteria, and list assumptions, conflicts, risks, and unresolved decisions.

`design.md` must describe the smallest design that could satisfy the approved
requirements. Include affected components and contracts, data and control
flow, failure behavior, compatibility, security, observability, resource
ownership, and verification approach. Cite repository paths for current-state
claims.

`tasks.md` must contain ordered checkable tasks linked to requirement IDs. Each
task names its bounded files or component, completion evidence, and relevant
test level. Leave unresolved design work blocked rather than hiding it inside
implementation.

All three documents are drafts. Keep Jira-to-requirement-to-design-to-task-to-
test traceability explicit.

## Boundaries and stop

Do not edit the story, source, tests, OpenWiki, `knowledge-base/`, graph data,
workspace steering, hooks, or prompts. Do not install dependencies, start an
application service, download a model, run inference, or perform a mutating MCP
operation.

When the lifecycle command returns `complete`, present the three paths,
evidence consulted, graph leads verified or rejected, unresolved decisions,
and the exact scope awaiting review. End at:

`GATE A — WAITING FOR HUMAN SPECIFICATION REVIEW`

Specification generation does not authorize implementation.
