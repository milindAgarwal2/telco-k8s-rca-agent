# Run AIDE Operational Diagnosis and Remediation

Run the reusable workflow `aide-operational-diagnosis-remediation` as the
`aide-coordinator`.

Read before using any environment tool:

1. `.aide/workflows/catalog.json`
2. `.aide/workflows/definitions/diagnose-remediate.md`
3. applicable project runbooks and repository instructions

The initial phase is strictly read-only. A diagnostic request does not grant
remediation permission.

## Scope and access intake

Confirm required agents and skills, then obtain:

- incident/reference ID, symptom, impact, start time, and time zone;
- exact environment and resource targets;
- approved read-only tools and excluded targets;
- sensitive-data handling boundary;
- recent changes, expected healthy state, and relevant runbooks;
- remediation approver and desired diagnosis-only or remediation-capable mode.

Never request a pasted credential. Stop when target identity is ambiguous or a
supposed read operation may mutate state.

## Diagnostic phases

1. As `aide-coordinator`, record the exact scope, observation interval,
   permissions, prohibited actions, and recovery signals.
2. As `aide-operations-investigator`, follow the applicable domain skill and
   `aide-runbook-handover`. Collect least-invasive, timestamped observations
   and map affected-resource relationships. Keep MCP/tools read-only.
3. Produce a diagnostic report that separates facts, inferences, hypotheses,
   unknowns, supporting evidence, and disconfirming evidence. Rank hypotheses;
   do not overstate the likely cause.

If the request is diagnosis-only, stop here with findings and proposed next
observations.

4. Propose the smallest remediation with exact target/action, prerequisites,
   impact, expected signals, observation window, rollback trigger, rollback
   action, and rejected alternatives. Do not execute it.

## Gate A — mutation approval

Display the current target state and timestamp, exact remediation, tool,
expected effect, blast radius, health checks, rollback, and unresolved risk.
End with `WAITING FOR TARGET-SPECIFIC REMEDIATION APPROVAL`.

The incident request, urgency, available write credentials, or approval of a
different command/target is not Gate A approval.

Only after exact approval:

5. Transition to `aide-release-operator` and follow
   `aide-bounded-execution`. Reconfirm target, current state, preconditions,
   authorization, and rollback readiness. Perform only the approved action.
   Stop on mismatch or unexpected effect; do not improvise another mutation.
6. Transition to `aide-verifier` and follow `aide-test-verification`. Collect
   fresh recovery signals, dependent-resource health, side effects, recurrence
   evidence, observation duration, and rollback status.

If the Kiro client cannot transition to the release operator, prepare the exact
execution hand-off and stop. Do not execute under a diagnostic-only agent.

Never run arbitrary scripts, expand privileges, access unapproved secrets,
perform an unapproved rollback, or silently turn failed observation into a
health conclusion.

On failure, preserve all observations and command output. Report current state,
last safe checkpoint, incomplete coverage, and exact human decision needed.


