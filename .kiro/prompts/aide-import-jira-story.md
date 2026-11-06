# Run AIDE Jira Story Import

Confirm that Kiro shows the Jira, read-only Neo4j, and Graphiti/memory MCP
servers as connected.

Import the exact Jira issue key supplied by the user through the configured
read-only Jira MCP get-issue operation.

Follow `aide-jira-story-import`: initialize the story lifecycle before writing
and create `jira/<KEY>-<capability-slug>.md` from the retrieved issue. Then
follow `aide-ears-story-refinement` on that same file. Preserve Jira
traceability, distinguish requested behavior from repository evidence, and do
not invent missing requirements.

Set `aide_stage: ears-ready` only after the required EARS story, acceptance
criteria, and traceability sections pass validation. The installed
`aide-story-lifecycle` hook will then request the Kiro specification. Stop at
Gate A for human review. Do not implement the feature or mutate Jira.

