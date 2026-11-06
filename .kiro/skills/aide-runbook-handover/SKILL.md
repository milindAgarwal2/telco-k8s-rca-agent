---
name: aide-runbook-handover
description: "Use when asked to create or update a method of procedure, deployment guide, troubleshooting guide, operational runbook, rollback plan, recovery plan, or support handover for an approved change."
---

# AIDE runbook and handover

Produce instructions an authorized operator can execute and verify without
guessing. Static documentation must not imply that an operation was performed.

## Procedure

1. Confirm the approved change, supported environments, operator role, and
   source evidence.
2. Define prerequisites, access, target-selection checks, required approvals,
   maintenance conditions, and backups or recovery points.
3. Document inputs, commands or actions, expected output, side effects,
   checkpoints, timeouts, and stop conditions.
4. Include pre-change health, deployment or method-of-procedure steps,
   post-change health, troubleshooting branches, and evidence capture.
5. Define rollback triggers and ordered rollback steps. If rollback is unsafe or
   impossible, say so prominently and give the approved recovery or escalation
   path.
6. Name ownership and escalation roles only when evidence supports them; use a
   placeholder requiring review otherwise.

## Output contract

A usable handover includes scope, exclusions, assumptions, prerequisites,
target identity, change window considerations, step-by-step procedure,
verification, monitoring, failure triage, rollback or recovery, evidence to
retain, ownership, and unresolved questions.

Represent secrets as named secure inputs, never literal values. Use exact
commands only when they are verified for the target; mark examples and
placeholders clearly. Require explicit confirmation before irreversible steps.

## Boundaries

Writing a runbook does not execute it. Do not access a live environment, invent
contact details, or describe an untested rollback as proven.
