---
name: aide-loop-engineering
description: Suggest, explain, design, create, or update a reusable repository engineering loop from an exact Jira issue, a local specification, plain-language intent, or repository discovery. Use before generating a bos-aide-loop run and Kiro launcher.
---

# AIDE loop engineering

Design the smallest useful loop and make it understandable before generating
artifacts. This skill prepares `bos-aide-loop` inputs; it does not execute the
loop or authorize implementation.

## Select the intake path

Use the first explicit source and combine sources only with clear labels:

| Input | Read-only intake |
| --- | --- |
| Exact Jira key | Retrieve only that issue through the configured Jira MCP; do not search broadly or write Jira |
| Local specification | Read the named workspace-relative requirements/design/tasks and retain its review state |
| Plain intent | Record desired behavior, then inspect relevant repository evidence |
| Suggest loops | Inventory the repository and compare two to four bounded, useful candidates |

If Jira cannot be read, stop that intake path and name the configuration gap.
Do not invent issue content. A user-supplied export may replace MCP intake only
when the user provides it. Reject spec paths outside the workspace.

## Build grounded context

Read applicable instructions, Git revision/status, `.aide/project.json`,
existing `loops/`, repository scripts, validation contracts, code, schemas,
tests, and protected paths. Use reviewed `knowledge-base/`, folder `SPECS.md`,
exact Neo4j, Graphiti, and OpenWiki as supporting context when available.

Keep desired behavior separate from current behavior. Source/tests and reviewed
specifications outrank generated knowledge. Cite the paths supporting the loop's
scope, commands, contracts, and acceptance mapping.

## Explain the proposal

Before any write, show:

- loop name, safe run ID, outcome, trigger, source binding, scope, exclusions;
- ordered phases, roles, tools, decisions, human gates, and dependencies;
- actual structured checks and their acceptance IDs;
- evidence directory, repair limit, resume inputs, and prohibited follow-ons;
- every exit: `READY_FOR_REVIEW`, `BLOCKED`, `LIMIT_REACHED`, `CANCELLED`, and
  `OUTCOME_UNKNOWN`.

Explain these in plain language and include a focused Mermaid flowchart with
success, repair, repair-limit, blocker, review, cancellation, and uncertain
outcome branches. For a suggestion request, compare two to four candidates and
diagram the recommended one. End with `WAITING_FOR_LOOP_APPROVAL` and the exact
files the selected proposal would create or update.

Do not treat a generic agreement as selecting among multiple candidates. Do not
write until the user accepts one exact proposal.

## Generate the accepted loop

Create two user-owned workspace artifacts:

1. `loops/runs/<run-id>.yaml`, based on
   `loops/templates/bos-aide-run.yaml` and schema
   `bos-aide-loop-run/v0.2`.
2. `.kiro/prompts/aide-loop-<run-id>.md`, a Kiro launcher that loads
   `bos-aide-loop`, reads the run, starts in `plan` mode, presents the bound
   plan/exit criteria, and stops at the execution approval gate.

Use repository-relative paths, a local operation target, the matching ignored
`.aide/local/loops/<run-id>` evidence directory, a nonnegative repair limit,
and structured checks containing an executable, string-list arguments,
working directory, timeout, expected evidence, and acceptance IDs. Never place
credentials, approval receipts, pipes, redirection, compound shell commands,
implicit downloads, or external mutation into the run.

Use actual repository commands only. When a required value cannot be grounded,
show the incomplete draft and ask one focused question; do not write it or call
it runnable. Validate generated artifacts against the accepted proposal and
report how to select the launcher. Do not invoke it automatically.

## Update and answer

For an existing loop, inspect its run, launcher, and ignored evidence. Propose a
diff and repeat the approval gate. Preserve user content, recorded repairs,
evidence, and outcomes. A new ID cannot reset an exhausted repair count.

For questions, remain read-only. Explain the relevant architecture and exit
criteria with a focused Mermaid diagram and cite the run/spec/source evidence.

## Boundaries and completion

Generation approval covers only the run and launcher. Execution still requires
the exact plan/revision/scope/check approval defined by `bos-aide-loop` and the
existing AIDE hooks. This role never implements code, executes checks,
self-approves, commits, pushes, opens or merges a PR/MR, deploys, mutates Jira,
publishes OpenWiki, or ingests graph data.

Return source/revision, evidence, architecture, diagram, checks/acceptance map,
repair and evidence policy, exits, unresolved decisions, artifact paths,
invocation guidance, and `SUGGESTED`, `WAITING_FOR_LOOP_APPROVAL`, `GENERATED`,
`REVIEW_REQUIRED`, or `BLOCKED`.
