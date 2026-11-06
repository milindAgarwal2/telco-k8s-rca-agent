# Run AIDE Repository Onboarding

Run the reusable workflow `aide-repository-onboarding` as the
`aide-coordinator`.

Before taking any repository action, read:

1. `.aide/workflows/catalog.json`
2. `.aide/workflows/definitions/onboard-repository.md`
3. all repository instruction files applicable to the selected scope

The installed workflow definition is controlling when this launcher is less
specific. The user's current request and repository instructions remain
higher-priority constraints.

## Start protocol

1. Confirm that the required AIDE agents and skills named in the catalogue are
   available. If one is missing, report it and stop before substituting an
   invented process.
2. Obtain the mandatory inputs from the definition: repository root, immutable
   revision, included/excluded paths, audience/depth, knowledge destination and
   reviewer, and approved read-only integrations.
3. Default only the repository root to the current workspace. Never guess the
   revision, sensitive exclusions, or reviewer.
4. Create a concise run header using the workflow-run template. Do not write a
   run file unless the user requests or approves that artifact.
5. State that generated knowledge is a draft and that repository scripts will
   not be executed merely because they are discovered.

## Execution protocol

Perform these phases in order and label each role transition:

1. `aide-coordinator` — select and preflight.
2. `aide-context-analyst` following `aide-repository-discovery` — discover
   structure, instructions, documentation, contracts, tests, and command
   candidates using read-only inspection.
3. `aide-context-analyst` following `aide-context-impact` — prepare the draft
   project profile and module/relationship map.
4. `aide-knowledge-curator` following `aide-knowledge-maintenance` — produce the
   source-linked knowledge candidate in the approved candidate location.
5. `aide-verifier` following `aide-test-verification` — check references,
   evidence coverage, contradictions, exclusions, and draft labels.

When the Kiro client cannot delegate to another agent, execute non-independent
roles sequentially and label them accurately. For verification that requires
independence, prepare a reviewer hand-off and stop for a fresh agent/session;
do not claim an independent check from the same context.

Use an MCP integration only when it is already configured, approved for this
repository, and read-only for the requested phase. Verify important MCP-derived
claims against the selected source revision. Never send repository content to
an unapproved provider.

## Mandatory stops

Stop before running any unreviewed repository command, installing a dependency,
changing source, publishing knowledge, or marking generated content as
authoritative.

At the final gate, present:

- selected repository and immutable revision;
- generated artifacts and exact paths;
- evidence coverage and exclusions;
- unresolved contradictions/questions;
- commands discovered and confirmation that unreviewed commands were not run;
- exact reviewer decision required.

End with `WAITING FOR HUMAN KNOWLEDGE REVIEW` unless the user has provided a
separate, current approval for the exact candidate revision. Earlier permission
to start onboarding is not publication approval.

On failure, preserve existing source and knowledge. Report the last completed
phase, partial artifacts, failure evidence, and smallest safe input required to
resume.


