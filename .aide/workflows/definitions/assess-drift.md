# Workflow: Drift and Health Assessment

## Metadata

- Workflow ID: `aide-drift-health-assessment`
- Trigger: a schedule or explicit assessment request.
- Coordinator: `aide-coordinator`
- Status: reusable read-only assessment protocol.

## Objective

Compare approved intent with fresh, time-bounded observations to identify stale
documentation, broken references, failed integrations, and unexpected
configuration or runtime differences. Produce findings or a proposed change,
not automatic repair.

## Do not use this workflow for

- executing a known remediation;
- declaring production health without fresh observations;
- treating generated knowledge as approved intent;
- broad vulnerability scanning without separate authorization;
- modifying configuration to make an assessment pass.

Use `aide-operational-diagnosis-remediation` for incident diagnosis and
`aide-approved-knowledge-maintenance` to correct approved knowledge.

## Mandatory inputs

1. Assessment scope and accountable requester or schedule owner.
2. Approved intent baseline and immutable revision/version.
3. Observation interval and freshness requirement.
4. Exact repository, documentation, integration, and runtime targets.
5. Approved read-only tools and excluded/sensitive data.
6. Expected health signals and classification thresholds.
7. Destination and owner for findings.

If approved intent, target identity, or observation freshness is unknown, record
the gap and do not classify the corresponding item as healthy or drifted.

## Roles and methods

| Responsibility | Agent | Skill |
| --- | --- | --- |
| Define baseline, scope, and checkpoint | `aide-coordinator` | `aide-task-planning` when available |
| Collect repository/document context | `aide-context-analyst` | `aide-repository-discovery` and `aide-context-impact` |
| Collect current external observations | `aide-operations-investigator` | Domain skill and `aide-runbook-handover` |
| Validate and rank findings | `aide-verifier` | `aide-test-verification` |

All integrations are read-only for this workflow. An unreachable target is an
observation failure, not evidence that it is healthy, unhealthy, or drifted.

## Phase 1: Select the baseline

The coordinator records:

- exact approved specification/configuration/knowledge revisions;
- authority and conflict rules for multiple baselines;
- included systems and deliberately excluded systems;
- expected values, relationships, references, or health conditions;
- freshness limits and observation time zone;
- read-only access boundary and sensitive-data rules;
- severity model and finding owner.

Output: immutable comparison plan.

Stop when two intended-state sources disagree in a way that changes comparison
results. Escalate the conflict to their owners.

## Phase 2: Collect fresh state

Collect only the approved observations required by the comparison. Examples:

- current repository revision, configuration keys, schemas, and dependencies;
- existence and targets of documentation links or source references;
- integration endpoint status and metadata without secrets;
- resource status, conditions, version, and relationships;
- bounded events, logs, metrics, queue depth, or database metadata;
- graph/index build status and source revision;
- age and review status of knowledge artifacts.

Every observation records target, timestamp, method, result, and limitation.
Keep raw sensitive evidence in its approved location and summarize safely.

Output: timestamped health snapshot and observation-coverage map.

## Phase 3: Compare expected and observed state

For each baseline item, classify:

- `matches`: evidence satisfies the stated intent;
- `drift-confirmed`: fresh evidence differs from intent;
- `stale-reference`: the referenced object or revision changed or disappeared;
- `integration-failed`: the integration was reached and returned a defined
  failure;
- `unobserved`: access, tool, or freshness prevented a comparison;
- `baseline-conflict`: approved intent is internally inconsistent;
- `not-applicable`: the item is demonstrably outside the selected scope.

Do not combine `unobserved` with healthy results. Link every classification to
both baseline and observation evidence.

Output: expected-versus-observed matrix and relationship impact map.

## Phase 4: Verify and rank

The verifier checks for stale caches, wrong targets, time-window mismatch,
partial access, transient failures, and unsupported causal claims. Re-observe a
small high-impact sample when safe and approved. Rank findings by:

- confirmed user/service impact;
- security or data risk;
- breadth of affected dependants;
- confidence and reproducibility;
- urgency relative to the baseline owner;
- cost and risk of leaving it unresolved.

Output: confirmed, suspected, and unverified finding register.

## Phase 5: Assessment hand-off

The coordinator reports:

- overall coverage and freshness;
- findings by severity and classification;
- evidence and affected relationships;
- false-positive limitations and unobserved areas;
- owner and recommended next workflow;
- proposed source, knowledge, integration, or operational change.

The report may recommend `aide-approved-change-delivery`,
`aide-approved-knowledge-maintenance`, or
`aide-operational-diagnosis-remediation`. It does not execute them
automatically.

## Human gates and stop conditions

Stop before:

1. repairing source, configuration, documentation, graph data, integration, or
   runtime resources;
2. escalating read-only access to mutation;
3. interpreting failed collection as a system-state conclusion;
4. changing the baseline during the assessment without starting a new
   comparison revision;
5. publishing sensitive observations outside their approved destination.

## Failure and resumption

Preserve partial observations with timestamps and explicit coverage gaps. A
retry after the freshness window starts a new observation set; it must not
silently overwrite earlier evidence. Resume comparison only when baseline and
target identity remain unchanged.

## Completion criteria

- Baseline and observation revisions/times are explicit.
- Every finding links expected and observed evidence.
- Unobserved areas are separate from passing results.
- No repair or environment mutation occurred.
- Each actionable finding has an owner and proposed next workflow.


