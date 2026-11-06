# Workflow: AIDE Regression Evaluation

## Metadata

- Workflow ID: `aide-regression-evaluation`
- Trigger: a hook, skill, agent, model, prompt, tool, or AIDE configuration
  changes.
- Coordinator: `aide-coordinator`
- Status: reusable comparative evaluation protocol.

## Objective

Compare a candidate AIDE configuration with the previous approved baseline on
the same representative tasks, repository revisions, tools, permissions,
models, budgets, and acceptance criteria. Report correctness, unintended
changes, human corrections, verification completeness, time, cost, failures,
and required-control results before a human promotion decision.

## Do not use this workflow for

- optimizing directly against hidden or held-out evaluation answers;
- changing acceptance criteria after seeing candidate results;
- comparing different task/repository/model/tool conditions as if controlled;
- claiming statistically general results from a single demonstration;
- promoting a candidate automatically.

## Mandatory inputs

1. Immutable approved baseline package/version.
2. Immutable candidate package/version and stated changes.
3. Representative task set and frozen repository revisions.
4. Acceptance rubric, required safety/control tests, and severity thresholds.
5. Model/deployment names, inference settings, tool permissions, and context
   policy for each condition.
6. Run count, ordering/randomization rule, time/cost budget, and isolation plan.
7. Human scorer/reviewer and promotion decision owner.

If baseline artifacts, task definitions, or required controls are mutable or
missing, stop before execution.

## Roles and methods

| Responsibility | Agent | Skill |
| --- | --- | --- |
| Freeze experiment and coordinate isolation | `aide-coordinator` | `aide-task-planning` when available |
| Execute and score the comparison | `aide-workshop-evaluator` | `aide-workshop-evaluation` |
| Verify artifacts and controls | `aide-verifier` | `aide-test-verification` |
| Review interpretation independently | `aide-reviewer` | `aide-change-review` |

Model and tool access must use approved internal configuration. The workflow
does not configure a new provider or silently fall back to another model.

## Phase 1: Freeze the experiment

Create an experiment definition containing:

- baseline and candidate checksums/revisions;
- exact tasks and selected repository revisions;
- seeded inputs or a documented nondeterministic sampling method;
- tool/MCP availability and permission profiles;
- model deployment, settings, and context window policy;
- expected output artifact and evaluation rubric per task;
- required control/safety tests and promotion thresholds;
- run isolation, reset, ordering, timing, and cost collection rules;
- known confounders and planned exclusions;
- scorer identities and conflict-resolution method.

Keep initial knowledge-ingestion or setup cost separate from subsequent task
performance unless the experiment explicitly evaluates onboarding.

Output: immutable experiment definition and run plan.

### Gate A: experiment approval

The human evaluator approves the exact definition before any scored run. A
change to task, revision, rubric, model, tools, permissions, budget, or control
tests creates a new experiment revision.

## Phase 2: Execute the comparison

Run baseline and candidate under equivalent, isolated conditions. For each run
record:

- condition and immutable configuration revision;
- task/repository revision;
- start/end time and model/tool usage where available;
- produced diff or artifact;
- commands/checks performed and failures;
- human intervention and its reason;
- stop/refusal behaviour;
- environment anomaly or contamination.

Do not allow the candidate to change its evaluated source, task, acceptance
criteria, held-out tests, or baseline artifacts. Reset the workspace between
conditions according to the approved plan.

Output: comparable baseline and candidate run records.

## Phase 3: Score and analyze

Use the frozen rubric to compute or assess:

- functional correctness and acceptance-criterion coverage;
- unintended/out-of-scope modifications;
- human corrections and clarification burden;
- verification completeness and unsupported claims;
- adherence to approval and access boundaries;
- error recovery and preservation of existing work;
- elapsed time and human active time;
- token/model/tool cost where available;
- failure rate, flaky outcomes, and severity distribution;
- setup/ingestion cost separately from repeat-task cost.

Report raw counts and denominators, not only percentages. Separate measured
results from interpretation and statistical uncertainty.

Output: metric table, per-task findings, and failure analysis.

## Phase 4: Verify experiment integrity

The verifier checks:

- checksums/revisions match the approved definition;
- conditions used the same task and repository inputs;
- no held-out or evaluated artifact was altered;
- exclusions follow the predeclared rule;
- required controls ran and their complete failures are retained;
- time and cost measurements use comparable boundaries;
- unsupported, contaminated, or missing runs are labelled;
- conclusions do not exceed sample size or evidence.

Any broken required control is a blocking result even when aggregate quality
improves.

Output: integrity report and validated metric set.

## Phase 5: Independent review and decision hand-off

The reviewer receives the frozen definition, raw results, scoring output,
integrity report, and candidate change. It produces:

- strongest demonstrated improvements;
- regressions by severity and affected workflow;
- confounders and unanswered questions;
- required corrections or additional runs;
- recommendation: promote, hold, reject, or limited pilot.

### Gate B: promotion decision

The human owner decides whether to promote the exact evaluated candidate. Do
not promote when a required control fails or results materially degrade beyond
the approved threshold. A changed candidate must be evaluated again.

## Human gates and stop conditions

Stop before:

1. scored execution without Gate A;
2. modifying held-out tests, tasks, criteria, or evaluated changes to improve a
   score;
3. silently substituting a model, provider, permission, or tool;
4. hiding failed/contaminated runs or incomplete verification;
5. promotion despite a blocking control or without Gate B.

## Failure and resumption

Preserve immutable run artifacts and failed output. Do not overwrite a failed
run with a retry; assign a new run identifier and record why. Resume only when
the experiment revision and isolation conditions remain valid. Otherwise start
a new experiment revision and retain the earlier result.

## Completion criteria

- Baseline and candidate conditions are reproducible and comparable.
- Metrics cover correctness, unintended changes, human correction,
  verification, time, cost, and failures.
- Required controls and experiment integrity are independently checked.
- Limitations and negative results are visible.
- Promotion remains a human decision tied to the evaluated candidate revision.


