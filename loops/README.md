# Reusable BOS AIDE engineering loop

Select a story and a run file instead of rewriting the engineering procedure
in every chat. The shared `bos-aide-loop` skill handles plan, execute, bounded
repair, evidence, and assisted resume for a small repository change.

## What AIDE installs

Both minimal and full/all overlays with the shared component copy:

| Baseline source | Installed project path |
| --- | --- |
| `catalog/skills/shared/bos-aide-loop/SKILL.md` | `.kiro/skills/bos-aide-loop/SKILL.md` |
| `catalog/loops/templates/bos-aide-run.yaml` | `loops/templates/bos-aide-run.yaml` |
| `catalog/loops/README.md` | `loops/README.md` |

Full/all also declares the same skill in its exact flavor catalog. The selected
AIDE coordinator and change engineer discover it through their skill resources;
their tool permissions remain unchanged. Other full custom agents discover the
full workspace catalog. This adds no MCP definitions or runtime dependencies.

The supplied starter is adapted to AIDE's existing approved-change procedure,
structured validation contracts, and ignored local evidence. The skill remains
on demand; it is not copied into always-on steering.

## Configure once per story

1. Copy `loops/templates/bos-aide-run.yaml` to a new reviewed
   `loops/runs/STORY-123.yaml`. Keep reusable commands in existing project
   scripts; reference those scripts from this small run definition.
2. Set a unique safe run ID, exact local story path, reviewed spec directory,
   explicit path scope, local operation target, and repair limit. A story may
   be exported from Jira through an already approved MCP integration or
   provided as local Markdown. Existing AIDE Jira/EARS/spec prompts can prepare
   the story/specification in a separate stage.
3. Configure the checks with actual executables, string-list arguments,
   working directories, bounded timeouts, expected evidence and acceptance
   mappings. Derive candidates from `.aide/project.json` validation contracts
   and repository scripts; review them before use. Blank required executables
   and an empty scope intentionally block execution. Add language-, model-,
   performance- or hardware-specific checks when the change requires them.
4. Use `.aide/local/loops/<run_id>` for evidence. Run definitions can be
   committed after review; ignored evidence, approvals, credentials, raw logs,
   and local run receipts must not be committed automatically.

For a reviewed structured command, the proposed contract may look like:

~~~yaml
name: unit-tests
required: true
executable: "<repository-approved-executable>"
args: ["<approved-test-argument>"]
working_directory: "."
timeout_seconds: 300
expected_evidence: "AC-1 behavior verified for the final change."
acceptance_ids: ["AC-1"]
~~~

The template chooses no language or test framework. A Java wrapper, a Go test
command, a Python uv command, a Bash check, or a Kubernetes/GitOps source
validation can each be represented with the actual repository-approved
executable/argument contract. An OS-specific wrapper invocation must be
reviewed explicitly. Remote targets, deployment, dependency installation,
credential changes, and graph publication are outside this local loop.

`bos-aide-loop-run/v0.2` is an AIDE agent-readable format, not a native Kiro
schema. Kiro interprets the YAML through the skill; the installer does not
execute or programmatically validate run definitions. The older starter v0.1
`command` strings need conversion to executable/args contracts, an explicit
local operation target, and the ignored evidence path before execution. Keep
its existing repair count and review/authorize any conversion as a plan change.

Once a run is configured, a team may keep a reviewed project-owned seed at
`loops/presets/<project>-run.yaml`. Copy that seed for later stories and update
only the story/spec paths, scope, run ID, acceptance mapping and evidence path.
Do not use a new run ID to silently reset an existing run's repair count. AIDE
does not own those presets.

## Plan first

Open Kiro at the installed repository root and submit this in chat:

~~~text
/bos-aide-loop Read loops/runs/STORY-123.yaml. Mode: plan.
~~~

This is a chat invocation, not a PowerShell command. Current public Kiro docs
support workspace skills and slash invocation with trailing task context:
[Kiro skills](https://kiro.dev/docs/skills/). No CLI-only placeholder
substitution is required. If your client does not expose the slash command,
explicitly ask it to read `.kiro/skills/bos-aide-loop/SKILL.md` and the run file
for a plan-only trial.

Plan mode reads context and returns the bounded tasks, files, command contracts,
acceptance map, repair limit, gates, and missing inputs. It does not create
files or execute build/test/scan commands. Drafting missing specs or editing a
run definition is a separate explicitly requested configuration stage.

## Execute the concrete approved plan

Review the returned plan and authorize that exact run, scope, revision, target,
checks, and spec/input contents under the project's existing approval policy.
Then request execution in the same session:

~~~text
I approve the displayed plan for STORY-123-attempt-01, including its scope,
local target, specification revision, check contracts and repair limit.
/bos-aide-loop Read loops/runs/STORY-123.yaml. Mode: execute.
~~~

The chat request does not replace a required helper/hook approval binding.
Use the existing AIDE/Kiro state and gate; record the actual authorization
reference. Do not create or forge a parallel approval receipt. A read-only
coordinator routes the implementation to an authorized change engineer through
its existing permission boundary; adding this skill grants no write access.
The normal verifier/reviewer handoffs still apply.

The loop is understand -> approved plan -> implement -> check intent ->
analyze failure -> bounded repair/recheck -> evidence -> human review. Initial
implementation/checks count as zero repairs; the default allows three
additional cycles. A repair count is persisted before each additional cycle.
Missing commands or infrastructure are blockers, not an invitation to repeat
repairs. Any change to scope, tests, checks, specs or the limit requires the
appropriate plan review before continuing.

## Resume deliberately

~~~text
/bos-aide-loop Read loops/runs/STORY-123.yaml. Mode: resume.
Reconcile saved evidence and authorization with the current worktree first.
~~~

The agent reads plan/progress/check evidence, keeps the previous repair count,
and verifies current spec/input/source fingerprints. Stale evidence or
unverifiable authorization returns to planning or a blocker. An interrupted
repair already marked in flight remains counted. Do not silently repeat an
uncertain mutation. Documents provide assisted resumption, not exactly-once
execution, automatic restart, authenticated approval or a hard retry cap.

## Evidence and hand-off

Each ignored run folder contains `plan.md`, `progress.md`, `checks.md`,
`summary.md`, and `knowledge-delta.md`, plus permitted non-sensitive logs.
The progress record includes the current phase/task, repair count/limit,
in-flight action, bindings/fingerprints, changed files, blockers and next step.
Checks record actual results on the current diff. Complete failures must remain
available subject to retention/redaction policy; record those limitations.

READY_FOR_REVIEW requires all required checks to pass on the final change,
evidence for all acceptance criteria and no unresolved blocking finding.
Other exits are BLOCKED, LIMIT_REACHED, CANCELLED and OUTCOME_UNKNOWN. These are
loop report labels, not new native Kiro workflow states. No commit, push,
PR/MR creation, merge, deployment, Jira mutation, OpenWiki update or graph
ingestion follows automatically. A knowledge delta is a proposal for the
separate knowledge-maintenance workflow.

## Extend without copying the procedure

Version the shared skill through normal review. Change only the small run
inputs per story and keep common verification logic in project scripts. For
cross-service work, use one reviewed contract plus separate bounded service
runs coordinated through the existing approved-change workflow. Optional
OpenWiki, Neo4j and Graphiti retrieval can supply supporting context when
already authorized; it does not replace source evidence or authorize writing
knowledge.

The existing hooks observe tool/task/stop events and enforce their configured
gates. This addition registers no hook and claims no new automatic repair or
checkpoint engine. Core installer/helper code stays on the Python standard
library; no YAML runtime parser is introduced.

## Azure IaC and deployment handoff

The reusable loop may author and validate repository Bicep/ARM within its normal
file scope and structured checks. It still stops at `READY_FOR_REVIEW` and does
not deploy. A full installation can hand the reviewed immutable IaC to
`aide-deploy-azure-infrastructure`, which creates a separate What-If plan and
requires plan-ID-bound operations approval. An Azure apply is never a loop
repair, automatic next step, or resumable blind retry. `OUTCOME_UNKNOWN` stops
both procedures for human reconciliation.

## Read-only client smoke test

1. In a disposable minimal project, configure a local story/spec/run and invoke
   plan mode; verify no files change and no build/test/scan runs.
2. In a disposable full project, verify slash discovery and coordinator/change
   engineer resources without widened tool permissions.
3. For an approved fixture change, cause one repairable check failure, verify
   the recorded count, fix it, and confirm final required-check/intent coverage.
4. Interrupt a repair after its increment is saved, then resume. Verify the
   count remains unchanged and stale checks are not reused. Change a spec or
   input; verify execution returns to planning.
5. Exhaust the repair limit or remove a required tool; confirm the correct
   exit, a reviewable summary and no external publication.

Automated checks verify overlay delivery, content parity between shared/full
catalogs, agent resources, source inventories, idempotency and preservation.
Live skill execution, limit adherence, hook dispatch and assisted resumption
remain unverified until the client smoke test is performed.
