# Workflow: Operational Diagnosis and Remediation

## Metadata

- Workflow ID: `aide-operational-diagnosis-remediation`
- Trigger: a reported incident or explicit diagnostic request.
- Coordinator: `aide-coordinator`
- Status: reusable protocol; target-specific access approval required.

## Objective

Collect fresh, timestamped observations using approved read-only access;
separate facts from hypotheses; identify the likely cause; propose the smallest
safe remediation; execute it only after explicit authorization; and verify
recovery with fresh evidence.

## Non-negotiable boundary

Diagnosis is read-only. It must not silently become remediation. The existence
of a likely fix, an incident ticket, tool access, or an urgent request does not
authorize mutation.

## Mandatory inputs

1. Incident/reference identifier and accountable requester.
2. Symptom, impact, start time, and relevant time zone.
3. Exact environment, cluster/account/project, namespace, service, database, or
   API target as applicable.
4. Approved read-only tools and explicit excluded targets.
5. Sensitive-data handling boundary.
6. Known recent changes, expected healthy state, and available runbooks.
7. Remediation approver and communication channel.

Do not ask the user to paste a secret. Stop if target identity is ambiguous or
the only available diagnostic method would mutate the environment.

## Roles and methods

| Responsibility | Agent | Skill |
| --- | --- | --- |
| Bind scope and preserve phase boundary | `aide-coordinator` | `aide-task-planning` when available |
| Collect and interpret observations | `aide-operations-investigator` | Domain skill plus `aide-runbook-handover` |
| Execute an approved mutation | `aide-release-operator` | `aide-bounded-execution` |
| Verify recovery independently | `aide-verifier` | `aide-test-verification` |

For Kubernetes, PostgreSQL, Ansible, GitOps, API, or security incidents, apply
the corresponding installed skill. MCP access is optional and must use the
least privilege needed for the current phase.

## Phase 1: Scope and safety

The coordinator records:

- target identifiers and the observation time window;
- reported symptom and business/technical impact;
- permitted read-only operations and prohibited actions;
- owners, communication expectations, and escalation path;
- data that must be redacted or not collected;
- success and recovery signals;
- whether the request is diagnosis-only or may later request remediation.

Output: diagnostic scope and access boundary.

Stop on ambiguous production target, broad credential request, or inability to
distinguish read-only from mutating operations.

## Phase 2: Collect observations

The operations investigator begins with the least invasive evidence and records
timestamps and exact targets. Depending on the approved domain, observations
may include:

- desired configuration and recent version/change history;
- resource status, relationships, events, conditions, and health endpoints;
- bounded logs and metrics for the incident window;
- API response metadata and safe request traces;
- deployment, job, controller, queue, database, or dependency state;
- comparison with a known healthy peer when approved;
- runbook expectations and their current applicability.

Do not collect secrets or unrestricted production records. Redact sensitive
values in summaries and retain raw approved evidence only in its designated
secure location.

Output: timestamped observation ledger and affected-resource relationship map.

## Phase 3: Diagnose

Classify statements explicitly:

- **Fact:** directly supported by a cited current observation.
- **Hypothesis:** a possible explanation with supporting and disconfirming
  evidence.
- **Inference:** a reasoned conclusion not directly observed.
- **Unknown:** a material gap and how it could be resolved safely.

Rank hypotheses by explanatory coverage, evidence strength, and risk of testing.
Prefer a safe discriminating observation over a speculative fix. Identify
likely cause only when the evidence warrants it; otherwise report ranked
hypotheses.

Output: diagnostic report with facts, hypotheses, likely cause, confidence,
contradictions, and unanswered questions.

For a diagnosis-only request, stop here and hand off the report.

## Phase 4: Propose remediation

The investigator proposes the smallest action that addresses the supported
cause and documents:

- exact target and command/API/manifest/action;
- intended state transition;
- preconditions and dependency checks;
- user and service impact;
- security and data risk;
- expected signals and observation window;
- rollback trigger, exact rollback action, and recovery alternative;
- actions considered but rejected;
- whether the proposal changes source-of-truth or only runtime state.

Output: remediation proposal, health-check plan, and rollback plan.

### Gate A: mutation approval

Stop. The human approver must authorize the exact target, action, timing, tool,
expected effect, health checks, and rollback. Approval is single-purpose and
expires if any of these change.

## Phase 5: Execute approved remediation

Only `aide-release-operator` performs this phase, and only when enabled and
explicitly authorized. Before mutation it repeats the target, confirms current
state and approval, and verifies rollback readiness.

During execution:

- run only the approved action;
- preserve complete output and timestamps;
- do not improvise a second mutation after failure;
- stop on target mismatch, changed precondition, unexpected blast radius,
  credential exposure, or rollback unavailability;
- initiate rollback only when it was authorized by the approval or when the
  human separately authorizes it.

Output: execution record or fail-closed refusal.

## Phase 6: Verify recovery

The verifier obtains fresh evidence for the agreed recovery signals, checks for
side effects and recurrence, and distinguishes immediate recovery from durable
resolution. Record:

- target state and health after action;
- original symptom status;
- dependent-resource health;
- error-rate/backlog/latency or domain-equivalent signals;
- observation duration and limitations;
- rollback status;
- follow-up source-of-truth or prevention work.

Output: recovery verification and hand-off.

## Human gates and stop conditions

Stop before:

1. any write, patch, apply, scale, restart, delete, failover, migration,
   mutating request, or deployment during diagnosis;
2. running an arbitrary or unreviewed script;
3. expanding target scope or privileges;
4. accessing secrets or unapproved sensitive records;
5. remediation without exact approval;
6. unapproved rollback or a second speculative repair.

## Failure and resumption

On tool or observation failure, do not report health or drift by absence.
Record the error, scope not observed, last successful timestamp, and safe
alternative. On remediation failure, preserve all output, stop mutation, report
current state, and request the next human decision. Resume only after target
identity, current observations, and authorization are refreshed.

## Completion criteria

- Diagnosis contains timestamped facts and ranked hypotheses.
- No mutation occurred before Gate A.
- Any executed remediation exactly matches the approved action and target.
- Recovery is supported by fresh observations or explicitly remains unverified.
- Follow-up work and residual risk are visible.


