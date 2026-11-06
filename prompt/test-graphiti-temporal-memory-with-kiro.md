# Kiro Prompt: Test Graphiti Temporal Memory

Use this after ingesting two controlled episodes about the same relationship,
where the later episode supersedes the earlier state. Replace every bracketed
value with data approved for the target repository.

---

You are working in the current repository. Perform a read-only test of
Graphiti temporal memory through the workspace `graphiti` MCP server.

```text
GRAPHITI_REQUIRED: true
GRAPHITI_TRANSPORT: workspace-mcp
EXPECTED_DATABASE: <non-production database>
EXPECTED_GROUP_ID: <project-scoped group>
SUBJECT: <component, policy, interface, or capability>
FORMER_STATE: <earlier fact that should now be invalid>
CURRENT_STATE: <replacement fact that should remain valid>
TRANSITION_TIME: <expected ISO-8601 boundary or unknown>
MAX_RESULTS: 10
QUESTION: How did <SUBJECT> change from <FORMER_STATE> to <CURRENT_STATE>?
```

Require concrete values for the database, group, subject, former state,
current state, and question. Stop as `BLOCKED` if any placeholder remains, the
database appears to be production, or the transport is not `workspace-mcp`.

Read `AGENTS.md` and applicable nested instructions. Use only the workspace
`graphiti` server's status, health, and search tools. Do not use generic memory,
direct Neo4j inspection, a CLI fallback, ingestion, episode addition, graph
mutation, package installation, service startup, login, or configuration
changes. Do not reveal credentials or complete episode bodies.

1. Call `@graphiti/spec_brain_graphiti_status` first. Require service
   `spec-brain-graphiti`, `read_only: true`, no mutation tools, complete semantic
   configuration, and the expected database and group.
2. Call `@graphiti/spec_brain_graphiti_health`. Require the same boundary and
   healthy Neo4j, language-model, and embedding dependencies.
3. Call `@graphiti/spec_brain_search_graphiti` once with the complete question
   and `MAX_RESULTS`.
4. Identify one former fact and one current fact about the same subject and
   relationship. Require fact identifiers, source episode identifiers,
   `valid_at`, and an explicit `invalid_at` value or null.
5. Normalize equivalent UTC representations. Pass temporal supersession only
   when the former fact has a non-null `invalid_at`, the current fact has null
   `invalid_at`, their transition boundary is consistent, and both facts came
   from the expected database and group. If `TRANSITION_TIME` is concrete,
   require the observed boundary to equal it.

Return:

| Check | Status | Bounded evidence |
| --- | --- | --- |
| MCP boundary | PASS/FAIL/BLOCKED | service, read-only flag, database, group |
| Dependency health | PASS/FAIL/BLOCKED | redacted health result |
| Former fact | PASS/FAIL | ID, short excerpt, interval, episode IDs |
| Current fact | PASS/FAIL | ID, short excerpt, interval, episode IDs |
| Supersession | PASS/FAIL | normalized transition boundary |
| Provenance and isolation | PASS/FAIL | database, group, episode IDs |
| Read-only execution | PASS/FAIL | operations used |

Overall `PASS` requires every check to pass. Use `FAIL` for completed checks
whose temporal or provenance invariants fail, and `BLOCKED` when the required
transport, configuration, target, or dependency cannot be established. End
with `Graphiti execution: CONFIRMED` only for an overall `PASS`.
