# Import a Jira Story and Start the AIDE Specification Loop

Use this prompt in Kiro with one exact Jira issue key:

Before the demo, confirm Kiro shows the Jira, read-only Neo4j, and
Graphiti/memory MCP servers as connected.

```text
Import Jira issue <PROJECT-123> for this repository.

Use the configured Jira MCP read-only get-issue operation and follow
`aide-jira-story-import`. Create the initialized
`jira/<KEY>-<capability-slug>.md` draft from the retrieved issue, then follow
`aide-ears-story-refinement` on that same file. Preserve traceability and do
not invent missing requirements.

Set `aide_stage: ears-ready` only after the EARS story passes the skill's
output checks. Saving that final stage invokes the installed
`aide-story-lifecycle` hook, which may draft the Kiro specification and must
stop at Gate A for human review. Do not implement the feature or mutate Jira.
```

Expected flow:

```mermaid
flowchart LR
    U[Exact Jira key] --> J[Read-only Jira MCP]
    J --> I[Initialized local Jira draft]
    I --> E[EARS refinement]
    E --> H[Story lifecycle hook]
    H --> S[Draft Kiro specification]
    S --> G[Gate A: human review]
```
