---
name: aide-bounded-execution
description: "Use when asked to implement one approved Kiro task or one explicitly bounded change. Enforces path, tool, target, iteration, approval, and verification limits and returns a reviewable change with PASS, ESCALATE, or FAIL evidence."
---

# AIDE bounded execution

Execute one approved task at a time. A task's boundaries and workspace policy
are part of its contract.

## Before changing anything

1. Read applicable instructions and the approved requirement, design, and task.
2. Restate the intended outcome, allowed paths, excluded paths, external
   targets, required approval, and completion evidence.
3. Inspect current state and existing patterns. Reuse nearby implementation,
   fixtures, helpers, and tests where appropriate.
4. If a critical assumption is invalid or the required action exceeds the
   authorized scope, stop before mutation and return `ESCALATE`.

## Execution rules

- Make the smallest coherent change that satisfies the task.
- Preserve unrelated user changes and avoid opportunistic cleanup.
- Never self-approve an external write, destructive action, deployment, or
  scope expansion.
- Keep credentials and sensitive values out of files, logs, and output.
- Add or update behavior-focused tests when the task requires implementation.
- Run the narrowest validation that proves the change; preserve useful failure
  output.
- Do not mark the task complete when required validation was skipped.

## Result contract

Return exactly one outcome:

- `PASS`: the requested change is complete and required evidence passed;
- `ESCALATE`: progress stopped safely because a decision, approval, target,
  credential, dependency, or scope change is required;
- `FAIL`: the attempt did not satisfy the task and no safe in-scope recovery
  remains.

Include changed paths, behavior implemented, commands run, results, checks not
run and why, known limitations, and the next authorized action. A local lint or
dry run cannot be presented as runtime recovery evidence.
