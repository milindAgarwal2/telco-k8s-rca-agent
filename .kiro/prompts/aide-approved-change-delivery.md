# Run AIDE Approved Change Delivery

Run the reusable workflow `aide-approved-change-delivery` as the
`aide-coordinator`.

Before acting, read:

1. `.aide/workflows/catalog.json`
2. `.aide/workflows/definitions/approved-change.md`
3. all repository instructions applicable to the selected files and domain

The definition controls the phase sequence and stop points. The request to run
this workflow authorizes intake and specification drafting only; it does not
pre-authorize implementation, remote submission, merge, or deployment.

## Intake

Confirm required agents and skills, then obtain:

- work-item reference or full request;
- repository root and immutable starting revision;
- business outcome and known acceptance criteria;
- included and excluded scope;
- specification approver and change owner;
- protected files/environments and permitted tools;
- requested delivery artifact.

Do not guess a missing acceptance criterion that materially changes behaviour.
Record facts, intended behaviour, assumptions, and unresolved findings
separately.

## Execute in phases

1. As `aide-context-analyst`, follow `aide-context-impact`. Establish current
   behaviour from source/tests/schemas, trace affected modules and contracts,
   check approved duplicate-work sources, and identify risks and unknowns.
2. As `aide-spec-planner`, follow `aide-spec-authoring`. Draft measurable
   requirements including normal, alternate, failure, recovery, compatibility,
   and security behaviour as relevant.
3. As `aide-architect`, follow `aide-architecture-contracts`. Define impacted
   boundaries, contracts/models, flow, state, errors, observability, migration,
   rollback, and unresolved design decisions.
4. As `aide-spec-planner`, follow `aide-task-planning`. Produce ordered tasks,
   an exact target allow-list, prohibited operations, and a requirement-to-test
   verification map.

## Gate A — specification approval

Stop and display:

- exact specification identifier/revision;
- starting repository revision;
- included and excluded targets;
- intended behaviour and acceptance criteria;
- validation/evaluation plan;
- unresolved findings and risks;
- operations that remain prohibited.

End with `WAITING FOR EXACT SPECIFICATION APPROVAL`. Do not treat the original
change request, general approval, or permission to draft specs as Gate A.

Only after the human approves that exact revision:

5. As `aide-change-engineer`, follow `aide-bounded-execution`. Reconfirm the
   baseline; modify only approved targets; reuse existing patterns, fixtures,
   and tests; stop on scope expansion or protected-path change.
6. As `aide-verifier`, follow `aide-test-verification`. Run only reviewed,
   applicable commands; retain complete failures; map evidence and skipped
   checks to requirements and risk.
7. Request an independent review using `aide-reviewer` and
   `aide-change-review`. If this client cannot create an independent context,
   prepare the review packet and stop so a fresh Kiro session can review it.
   Never describe a same-context self-review as independent.
8. Resolve accepted findings inside the approved scope and rerun affected
   validation. Return to Gate A for material specification or target change.

Use `aide-security-reviewer` when sensitive boundaries are affected. Use MCP
tools only when separately approved and within the current phase's access
mode.

## Gate B — delivery hand-off

Prepare a PR/MR draft and evidence package containing change intent, exact
diff/targets, specification link, tests/evaluations and results, review
findings, unrun checks, residual risk, and required AI-assistance attribution.

End with `WAITING FOR DELIVERY DECISION`. Do not push, open a remote PR/MR,
merge, deploy, publish, or close the work item unless the user gives separate
explicit authorization for that exact action and target.

On failure, preserve user changes. Report approved revision, current diff,
completed tasks, failing evidence, last valid gate, and exact resume condition.


