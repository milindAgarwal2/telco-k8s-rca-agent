# Workflow: Approved Change Delivery

## Metadata

- Workflow ID: `aide-approved-change-delivery`
- Trigger: an approved feature, defect, or operational change is selected.
- Coordinator: `aide-coordinator`
- Status: reusable protocol; project adaptation required.

## Objective

Turn a bounded change request into an evidence-backed specification, obtain
human approval for an exact revision and target set, implement only that scope,
validate it, obtain an independent review, and prepare a pull-request (PR) or
merge-request (MR) evidence package. Merge and deployment are not implied.

## Do not use this workflow for

- an untriaged idea without an accountable requester;
- emergency mutation before incident scope and authorization exist;
- implementation whose duplicate-work or repository-contribution checks fail;
- changing held-out acceptance criteria to make an implementation pass;
- combining unrelated cleanup with the approved change.

## Mandatory inputs

1. Work-item reference or complete user request.
2. Repository root and selected starting revision.
3. Business outcome and acceptance criteria known at intake.
4. Initial included and excluded scope.
5. Specification approver and change owner.
6. Protected files/environments and permitted tool boundary.
7. Required delivery artifact: local patch, commit candidate, PR/MR draft, or
   another explicitly named hand-off.

Approval that says only “do it” is not a specification approval until its exact
specification revision, scope, and targets are recorded.

## Roles and methods

| Responsibility | Agent | Skill |
| --- | --- | --- |
| Coordinate state and gates | `aide-coordinator` | `aide-task-planning` |
| Discover current behaviour and impact | `aide-context-analyst` | `aide-context-impact` |
| Draft requirements and verification mapping | `aide-spec-planner` | `aide-spec-authoring` |
| Define contracts and design | `aide-architect` | `aide-architecture-contracts` |
| Produce ordered bounded tasks | `aide-spec-planner` | `aide-task-planning` |
| Implement approved tasks | `aide-change-engineer` | `aide-bounded-execution` |
| Validate requirements and regressions | `aide-verifier` | `aide-test-verification` |
| Independently review the change | `aide-reviewer` | `aide-change-review` |

Use `aide-security-reviewer` when authentication, authorization, credentials,
sensitive data, exposed services, or material permission boundaries change.

## Phase 1: Intake and context

The context analyst must:

1. Bind the request to the current repository and starting revision.
2. Read applicable repository instructions.
3. Check for existing implementations, related issues, specifications, tests,
   and duplicate work using approved read-only access.
4. Trace affected modules, interfaces, contracts, data, configuration, tests,
   documentation, operations, and customers.
5. State present behaviour and evidence separately from intended behaviour.
6. List assumptions, contradictions, unknowns, risk, and likely verification.

Output: evidence-backed context and impact report.

Stop if the requested change is duplicate, prohibited, trivial busywork under
the repository policy, or depends on unresolved high-impact requirements.

## Phase 2: Specify and plan

Prepare a meaningful specification set appropriate to the project. It should
include requirements, design, and tasks unless a smaller reviewed form is
explicitly accepted.

Requirements must define:

- outcome, actors, triggers, inputs, outputs, preconditions, and constraints;
- normal, alternate, failure, recovery, compatibility, and security behaviour;
- measurable acceptance criteria and unresolved questions.

Design must define:

- impacted architecture and boundaries;
- contract/model/schema changes and compatibility;
- control and data flow;
- state, concurrency, retries, timeouts, idempotency, and error handling where
  relevant;
- observability, rollback, migration, and deployment considerations without
  authorizing deployment.

Tasks must be ordered, independently checkable where possible, mapped to
requirements, bounded to named targets, and paired with verification evidence.

Output: versioned specification revision, target allow-list, verification map,
and unresolved-finding list.

### Gate A: specification approval

Stop and ask the human approver to accept or reject the exact specification
revision, target allow-list, prohibited operations, and verification plan.

An approval becomes stale if requirements, design, tasks, target set, selected
revision, or control configuration changes materially. Return to this gate.

## Reusable story loop entry point

For an explicitly requested service/story implementation loop, use the shared
`bos-aide-loop` skill with a reviewed `loops/runs/<story>.yaml` definition.
The installed `loops/README.md` explains plan/execute/resume, structured check
contracts, ignored evidence and persisted repair counts. This is a reusable
procedure for the implementation/verification stages below; it preserves Gate A,
review requirements and existing approval/hook state. It adds no runner, second
approval ledger or automatic external delivery/knowledge publication.

## Phase 3: Bounded implementation

After Gate A only, the change engineer:

- confirms the worktree still matches the approved baseline;
- modifies only approved targets;
- follows repository instructions and existing patterns;
- reuses existing tests, fixtures, and helpers before creating new ones;
- avoids unrelated formatting, cleanup, dependency, or configuration changes;
- records deviations and stops when scope expansion is needed;
- never edits approval, evaluation, or held-out test artifacts to manufacture
  success.

Output: implementation diff plus requirement/task traceability.

Stop immediately on protected-path modification, unexpected generated changes,
credential discovery, ambiguous migration, unapproved external mutation, or
material design divergence.

## Phase 4: Validate

The verifier selects the narrowest safe checks that prove the changed
behaviour, then expands according to risk and project guidance. Record:

- exact command or inspection performed;
- preconditions and environment;
- result, duration, and evidence location;
- requirement or risk covered;
- skipped or unavailable checks and why;
- full failure output location.

Model, performance, hardware-specific, integration, migration, or operational
changes require the corresponding evidence; a local unit test is not presented
as proof of an unrun environment-specific check.

Output: verification matrix and residual-risk report.

## Phase 5: Independent review

Use a fresh review context when practical. The reviewer receives the approved
specification, starting revision, complete diff, validation evidence, and
known limitations. Review for:

- requirement and design compliance;
- correctness and failure behaviour;
- unintended or out-of-scope change;
- contract, compatibility, security, and operational risk;
- test quality and missing verification;
- documentation or knowledge impact.

Findings must include severity, exact evidence, impact, and a concrete
resolution. The implementer resolves accepted findings and validation is rerun
where affected.

### Gate B: findings acceptance

Stop for human acceptance when a material finding is unresolved, waived, or
changes the approved specification. Reapproval is required for substantive
scope or design change.

## Phase 6: Delivery hand-off

Prepare, but do not automatically submit:

- PR/MR title and description;
- work-item and specification links;
- duplicate-work explanation when required;
- file/change summary;
- exact tests/evaluations run and results;
- security/operational/compatibility notes;
- unresolved risks and unrun checks;
- AI-assistance disclosure and attribution required by repository policy;
- merge, deployment, and rollback notes as proposals only.

Opening a remote PR/MR, pushing, merging, deploying, or closing the work item
requires separate explicit authorization at the time of that action.

## Human gates and stop conditions

Stop before:

1. implementation without Gate A approval;
2. any target, requirement, design, or test-strategy expansion;
3. continuing through unresolved high-impact findings;
4. use of a mutating external tool outside the approved task boundary;
5. push or remote PR/MR creation without explicit authorization;
6. merge or deployment without their own explicit authorization.

## Failure and resumption

Leave user changes intact. Do not reset, discard, or conceal a failing state.
Record the approved revision, current diff, completed tasks, failing evidence,
last valid gate, and exact next decision. Resume only after confirming that the
baseline and approvals are still current.

## Completion criteria

- The implementation matches the approved specification and target set.
- Required verification is passed or explicitly unresolved and accepted.
- Independent review is complete and findings are resolved or recorded.
- The hand-off is ready for a human PR/MR decision.
- No merge, deployment, publication, or unapproved external mutation occurred.


