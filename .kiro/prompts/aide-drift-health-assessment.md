# Run AIDE Drift and Health Assessment

Run the reusable workflow `aide-drift-health-assessment` as the
`aide-coordinator`.

Read first:

1. `.aide/workflows/catalog.json`
2. `.aide/workflows/definitions/assess-drift.md`
3. applicable project instructions, approved baselines, and runbooks

This workflow is read-only and produces findings or a proposed follow-up. It
must not automatically repair source, documentation, integrations, graphs, or
runtime resources.

## Intake

Confirm required agents and skills, then obtain:

- assessment scope and accountable owner;
- immutable approved intent baseline;
- observation interval and freshness requirement;
- exact repository, knowledge, integration, and runtime targets;
- approved read-only tools and sensitive-data exclusions;
- expected health signals and classification thresholds;
- findings destination and owners.

Do not guess approved intent. A failed or unavailable observation is not proof
that a target is healthy, unhealthy, or drifted.

## Execute in phases

1. As `aide-coordinator`, freeze the baseline, scope, expected state, freshness
   rule, classification model, and access boundary. Stop on a material conflict
   between intended-state sources.
2. As `aide-context-analyst`, follow `aide-repository-discovery` and
   `aide-context-impact` for repository, specification, reference, and
   knowledge evidence.
3. As `aide-operations-investigator`, follow the applicable domain skill and
   `aide-runbook-handover`. Collect current read-only observations with target,
   timestamp, method, result, and limitation.
4. Compare each expected item and classify it as `matches`, `drift-confirmed`,
   `stale-reference`, `integration-failed`, `unobserved`,
   `baseline-conflict`, or `not-applicable`. Link both baseline and observed
   evidence.
5. As `aide-verifier`, follow `aide-test-verification`. Check target, freshness,
   cache, partial access, transience, and causal-claim limitations. Rank
   confirmed, suspected, and unverified findings by impact and confidence.

Use MCP integrations only when approved and read-only. Keep sensitive raw data
in its designated location and summarize it safely.

## Handoff boundary

Report coverage/freshness, prioritized findings, evidence, affected
relationships, unobserved areas, false-positive limitations, named owners, and
the recommended next workflow.

End with `ASSESSMENT COMPLETE — NO REPAIR PERFORMED`.

Do not edit the baseline during the run, escalate permissions, repair a target,
or launch a remediation/change workflow automatically. On collection failure,
preserve timestamped partial evidence and state what could not be concluded.


