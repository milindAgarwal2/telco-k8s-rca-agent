---
name: aide-task-planning
description: "Use after requirements and design are approved to create or refine Kiro tasks.md. Decomposes the change into bounded, ordered tasks with dependencies, allowed resources, verification, approval gates, rollback, and escalation conditions."
---

# AIDE task planning

Turn an approved change into executable units without hiding decisions inside
task wording.

## Procedure

1. Confirm the approved requirements and design revision. If either is missing
   or materially contradictory, stop planning that portion and identify the
   decision needed.
2. Trace each task to requirement and design identifiers.
3. Decompose by independently verifiable behavior, not by arbitrary file count.
4. For every task define intent, in-scope files or resources, exclusions,
   inputs, output, dependencies, contract impact, and completion evidence.
5. Put prerequisite contracts, models, migrations, fixtures, and safety checks
   before dependent implementation.
6. Separate tasks that can run locally from tasks requiring hardware, a lab,
   credentials, a cluster, or another repository.
7. Add explicit approval gates before external mutations, deployments, data
   changes, or destructive operations.
8. State rollback or recovery steps and escalation conditions for risky tasks.

## Task contract

Each task must be small enough for one reviewable iteration and must identify:

- stable task identifier and traced requirements;
- outcome and observable completion criteria;
- allowed repository paths, tools, and external targets;
- prohibited or out-of-scope changes;
- ordered dependencies;
- validation command or other evidence;
- approval, rollback, and escalation conditions;
- status left unclaimed until evidence exists.

For cross-service work, create separate local tasks with an explicit interface
contract between them. Do not assume changes in another repository are already
deployed.

## Boundaries

Planning does not implement the tasks, grant credentials, authorize a target,
or approve requirements. Avoid opportunistic cleanup tasks unrelated to the
requested outcome.
