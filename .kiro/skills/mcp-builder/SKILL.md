---
name: mcp-builder
description: "Use only when asked to design, implement, test, or evaluate a genuinely missing Model Context Protocol server or tool. Do not use for configuring, installing, connecting to, or troubleshooting an existing MCP server."
---

# Build an MCP server

Adapted from the MCP server workflow in `anthropics/skills` for Kiro and this
workspace. First prove that an existing approved server or direct interface does
not already meet the need.

## Decision gate

Document the missing capability, users, target system, existing alternatives,
why composition is insufficient, data sensitivity, and expected maintenance.
If the request is only to use, configure, install, or repair an existing MCP
server, stop using this skill and follow that server's documentation.

## Design workflow

1. Define bounded user journeys and the minimum tools or resources needed.
2. Choose transport based on deployment: standard input/output for a local
   process or authenticated streamable HTTP for a managed service.
3. Design small, typed schemas with clear names, descriptions, defaults,
   pagination, timeouts, and deterministic error shapes.
4. Make read-only and mutating tools visibly distinct. Require explicit targets
   and confirmation semantics for material writes.
5. Keep credentials out of source and logs. Define authentication, authorization,
   tenancy, redaction, and audit behavior.
6. Bound payloads, pagination, retries, rate limits, cancellation, and partial
   failure. Never return unbounded repository, log, or database content.
7. For Python, obey the repository's `uv` requirement. Reuse the selected MCP
   SDK and pinned project dependencies rather than inventing a protocol layer.
8. Test schema validation, happy path, empty results, permission failure,
   timeout, unavailable dependency, pagination, redaction, and mutation gates.
9. Evaluate the server with fixed representative tasks and near-miss tasks.

## Output contract

Return capability decision, architecture, threat and data boundary, tool/resource
contracts, implementation, configuration template without secrets, tests,
evaluation results, install instructions, and known limitations.

Never enable a new server, write user-level Kiro configuration, or contact its
target system unless those actions are explicitly in scope.
