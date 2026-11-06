# Kiro Workflow Prompt Specifications

## Intent

These files are local Kiro `@prompt` launchers. Each launcher tells the selected
AIDE coordinator to load the corresponding installed workflow definition,
collect mandatory inputs, execute only the current authorized phase, and stop
at human gates.

`aide-import-jira-story.md` is a focused launcher for exact-key Jira intake.
It composes the installed Jira import and EARS refinement skills; the story
lifecycle hook invokes Spec Brain and specification authoring after readiness.

## Contract

- The installed definition is the workflow authority when a summary differs.
- A prompt does not grant tool, mutation, merge, publication, or deployment
  permission.
- Missing agents or required skills cause a safe stop, not improvisation.
- A role transition is labelled, and independence is not claimed unless a
  separate reviewer context actually performs the review.
- Failure reports preserve prior work and state the next resumable action.

## Inputs and outputs

The user supplies the workflow-specific subject, immutable revision or
observation time, scope, owners, and access boundaries. Outputs are the phase
artifacts and gate/checkpoint summaries defined by the linked protocol.

