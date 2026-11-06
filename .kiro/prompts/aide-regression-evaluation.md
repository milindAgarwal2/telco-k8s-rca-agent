# Run AIDE Regression Evaluation

Run the reusable workflow `aide-regression-evaluation` as the
`aide-coordinator`.

Read first:

1. `.aide/workflows/catalog.json`
2. `.aide/workflows/definitions/evaluate-aide.md`
3. applicable evaluation, repository, model, and tool-access instructions

This is a controlled comparison. Do not alter tasks, held-out tests, acceptance
criteria, evaluated source, or failed results to improve the candidate score.

## Intake and experiment freeze

Confirm required agents and skills, then obtain:

- immutable approved baseline and candidate revisions;
- frozen task set and repository revisions;
- acceptance rubric, required controls, and promotion thresholds;
- model/deployment, settings, tools, permissions, and context policy;
- run count, ordering/randomization, isolation, time, and cost budget;
- human scorer/reviewer and promotion owner.

As `aide-coordinator`, prepare an immutable experiment definition including
checksums/revisions, conditions, artifacts, reset rules, confounders, and
exclusions. Keep initial setup/knowledge-ingestion cost separate from repeat
task performance unless onboarding is the explicit subject.

## Gate A — experiment approval

Present the exact experiment revision and end with
`WAITING FOR EXPERIMENT-DEFINITION APPROVAL`. Do not start scored runs from a
draft definition. Any material condition change creates a new revision.

Only after Gate A:

1. As `aide-workshop-evaluator`, follow `aide-workshop-evaluation`. Run baseline
   and candidate under equivalent isolated conditions. Preserve run identity,
   times, artifacts/diffs, commands, failures, interventions, refusal behaviour,
   usage/cost where available, and contamination.
2. Score with the frozen rubric: correctness, unintended changes, human
   corrections, verification completeness, boundary adherence, recovery,
   elapsed/human time, cost, failure rate, and severity. Report raw counts and
   denominators and distinguish measurement from interpretation.
3. As `aide-verifier`, follow `aide-test-verification`. Check revisions,
   condition equivalence, held-out artifact integrity, declared exclusions,
   required controls, complete failure evidence, and conclusion limits.
4. Obtain an independent `aide-reviewer` assessment following
   `aide-change-review`. If no independent context is available, prepare the
   packet and stop for a fresh session; do not claim self-review independence.

Never silently substitute a model, provider, tool, permission, or repository
revision. Assign a new run ID to every retry and retain the failed run.

## Gate B — promotion decision

Present improvements, regressions, required-control results, confounders,
unanswered questions, and a promote/hold/reject/limited-pilot recommendation.
End with `WAITING FOR HUMAN PROMOTION DECISION`.

Do not promote a candidate that breaks a required control or materially
degrades beyond the approved threshold. A changed candidate must be evaluated
again. On failure, preserve immutable artifacts and state the exact safe resume
condition.


