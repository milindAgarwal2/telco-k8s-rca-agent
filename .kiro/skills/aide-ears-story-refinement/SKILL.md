---
name: aide-ears-story-refinement
description: "Use after a Jira issue has been imported into the active local Jira lifecycle file. Converts the retrieved source into a traceable EARS user story, validates the required sections, and marks the same file ears-ready so the specification hook can run."
---

# AIDE EARS story refinement

Refine the active imported Jira story without changing its requested intent.

## Procedure

1. Read the active story path from
   `.aide/full/hook/.state/workflow.json`. Require the
   file's `jira_key` to match the workflow and its stage to be
   `jira-imported`.
2. Follow
   `prompt/generate-ears-user-story-from-jira-or-user-request.md`, supplying
   the already retrieved local story as `JIRA_SOURCE`. Do not call Jira again
   during conversion.
3. Use repository source, tests, `knowledge-base/`, folder `SPECS.md` files,
   and OpenWiki only as read-only current-state evidence. Keep requested intent,
   verified current behavior, assumptions, and unknowns distinct.
4. Update the same file. It must contain:
   - a `## User story` section with `As a / I want / so that`;
   - `## EARS functional requirements` with stable IDs and at least one
     normative `THE SYSTEM SHALL` statement;
   - `## Acceptance criteria` with observable scenarios; and
   - `## Traceability` mapping material Jira statements to requirements or
     explicit dispositions.
5. Validate that every normative Jira statement is represented or explicitly
   unresolved. Set `aide_stage: ears-ready` only as the final edit.

Saving an EARS-ready story invokes the lifecycle hook. The hook may draft
`requirements.md`, `design.md`, and `tasks.md` in the derived Kiro spec
directory, then stops at human specification review.

The Kiro demo requires the Jira MCP for intake and read-only Neo4j plus
Graphiti/memory MCP connections for the specification context loop.

## Boundaries

Do not invent acceptance criteria, design choices, owners, estimates, or current
behavior. Do not implement code, approve the generated specification, or write
to Neo4j or Graphiti. Do not use this skill for raw Jira retrieval or an
uninitialized story file.
