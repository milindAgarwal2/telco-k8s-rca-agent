---
name: aide-jira-story-import
description: Use when the user supplies one exact Jira issue key and asks Kiro to retrieve it through the configured Jira MCP and create a local story. Fetches one issue read-only, initializes the AIDE lifecycle, writes a source-faithful draft under jira/, and hands it to the EARS refinement skill.
---

# AIDE Jira story import

Retrieve one Jira issue and turn it into the local input for specification
authoring.

## Procedure

1. Require one exact key matching `PROJECT-123`. Do not substitute a search
   query, URL, or guessed issue.
2. Use the configured Jira MCP's read-only get-issue tool. Request the summary,
   description, acceptance criteria, issue type, labels, and relevant comments.
   Treat comments as context unless the issue or user marks them as approved
   requirements.
3. Stop if the issue cannot be retrieved. Never invent inaccessible Jira
   content or switch to a write-capable Jira operation.
4. Derive a short lowercase capability slug from the summary. Use
   `jira/<KEY>-<slug>.md`; update that exact file if it already represents the
   same issue.
5. Before writing, initialize the lifecycle:

   ```powershell
   uv run --project .aide/full/hook --offline --frozen aide-hook init-story --jira-key <KEY> --story-path jira/<KEY>-<slug>.md --plan-revision r1
   ```

6. Write the retrieved source into that file with this frontmatter:

   ```yaml
   ---
   jira_key: <KEY>
   source: jira-mcp
   aide_stage: jira-imported
   status: draft
   ---
   ```

   Preserve the summary, description, source acceptance criteria, relevant
   context, and unresolved conflicts. Omit credentials, personal data, and
   unrelated comments.
7. Apply `aide-ears-story-refinement` to the same file. Do not create a second
   story artifact.

## Boundaries

The exact Jira read authorized by the user's key does not authorize Jira
updates, broad Jira searches, source changes, specification approval, or
implementation. Do not mark `aide_stage: ears-ready` until the refinement
skill's output contract is satisfied.

Use this skill for exact Jira-key intake. Do not activate it for pasted request
text, issue discovery, backlog triage, or Jira mutation.
