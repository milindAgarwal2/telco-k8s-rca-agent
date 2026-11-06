# `.kiro/skills/spec-brain` Folder Specification

## Intent

This folder defines Kiro's retrieval-first specification workflow. It ensures
Kiro consults exact Neo4j module and cross-service relationships before
Graphiti semantic context when creating requirements, design, tasks, or impact
analysis.

## Inputs and outputs

Inputs are the user's unchanged request, explicit target paths, configured local
services, and context returned by the workspace `graphiti` MCP server or the
   preconfigured `.aide/full/spec-brain` CLI fallback. Outputs are draft Kiro
specifications based on the repository's knowledge-primary, OpenWiki-secondary
template.

## Contracts and failure behavior

The skill must stop when service checks, retrieval, primary-context discovery,
or context budgeting fails. It must not substitute unsupported model guesses,
configure credentials, switch providers, edit application source, or implement
the requested change without separate authorization.

The skill must prefer `@graphiti/spec_brain_graphiti_status`, then the
group-scoped search or combined-context tools. It must never treat Kiro's
generic `memory` MCP as the repository Graphiti transport. CLI fallback is
permitted only when its environment was configured before the request.

## Interaction points

- `.aide/full/spec-brain/tools/spec_brain/` supplies checked retrieval context.
- `.kiro/settings/mcp.json` launches the read-only workspace `graphiti` server.
- `prompt/kiro-spec-template-knowledge-primary-openwiki-secondary.md` supplies
  the specification structure and evidence labels.
- `knowledge-base/`, including a reviewed knowledge-plane descriptor, is
  primary context; `openwiki/` is secondary context.
