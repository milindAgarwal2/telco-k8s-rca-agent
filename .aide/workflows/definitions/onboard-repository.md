# Workflow: Repository Onboarding

## Metadata

- Workflow ID: `aide-repository-onboarding`
- Trigger: a participant selects a repository and an immutable revision.
- Coordinator: `aide-coordinator`
- Status: reusable protocol; project adaptation required.

## Objective

Create a trustworthy starting context for contributors who do not yet know the
repository. The workflow inventories the project, identifies its real
instructions and validation mechanisms, prepares a project profile, and
produces a source-linked knowledge candidate. It does not claim that generated
knowledge is already correct or approved.

## Do not use this workflow for

- implementing a feature or fixing a bug;
- executing arbitrary setup, build, test, installation, or deployment scripts;
- scanning a live production environment;
- publishing a wiki or graph as authoritative without review;
- bypassing repository-specific contributor instructions.

Use `aide-approved-change-delivery` for implementation and
`aide-drift-health-assessment` for an established project's health review.

## Mandatory inputs

1. Repository root or source-control location.
2. Full commit identifier, signed tag, or other immutable revision.
3. In-scope modules and explicitly excluded or sensitive paths.
4. Requested depth and intended audience.
5. Knowledge output location and the person responsible for reviewing it.
6. Whether any read-only repository or knowledge integration is approved.

If the revision is mutable, access boundaries are unknown, or a required
credential would need to be copied into chat, stop before discovery.

## Roles and methods

| Phase responsibility | Agent | Skill |
| --- | --- | --- |
| Coordinate scope and checkpoints | `aide-coordinator` | `aide-task-planning` when available |
| Discover structure and project guidance | `aide-context-analyst` | `aide-repository-discovery` |
| Relate modules, contracts, and impacts | `aide-context-analyst` | `aide-context-impact` |
| Prepare the knowledge candidate | `aide-knowledge-curator` | `aide-knowledge-maintenance` |
| Check evidence, links, and gaps | `aide-verifier` | `aide-test-verification` |

Approved read-only MCP tools may accelerate inventory or retrieval. Their
result is evidence to verify, not an authority that overrides the selected
source revision.

## Phase 1: Select and preflight

The coordinator must:

1. Resolve the exact repository root and immutable revision.
2. Record current branch/worktree state without modifying it.
3. Find applicable repository instructions, including nested instruction files.
4. Identify available languages and tools without installing dependencies.
5. Confirm included, excluded, sensitive, generated, and vendored areas.
6. Confirm the knowledge destination and reviewer.
7. Classify each proposed command as read-only, locally mutating, externally
   mutating, or unknown.

Output: a preflight record with revision, scope, instructions, prerequisites,
and command classifications.

Stop if the repository cannot be bound to the selected revision, applicable
instructions conflict, or safe read-only discovery is impossible.

## Phase 2: Discover

The context analyst performs static, read-only discovery first:

- map top-level and important nested folders;
- identify language, build, package, test, deployment, configuration, and
  documentation artifacts;
- find existing architecture, requirements, design, task, runbook, and
  ownership information;
- locate source-defined contracts, schemas, public interfaces, tests, fixtures,
  and validation configuration;
- identify likely build, lint, test, and evaluation commands from repository
  evidence without executing them;
- identify generated, vendored, binary, secret-bearing, or production-data
  paths that knowledge generation must exclude;
- record contradictions and missing explanations.

Every material statement must link to an exact path and revision where
possible. Separate direct evidence, inference, and unresolved questions.

Output: repository inventory, module map, validation-command candidates, and
unresolved-question register.

## Phase 3: Prepare the project profile

Complete a copy of `project-profile.template.md` using discovered evidence.
The profile must include:

- repository identity and revision;
- project classification;
- evidence authority and disagreement handling;
- primary and secondary knowledge locations;
- proposed validation commands, preconditions, side effects, and evidence;
- protected targets and sensitive-data boundaries;
- approved integrations and access mode;
- named decision/review owners;
- unresolved setup questions.

Do not mark an observed command as approved. Human review of a command is a
separate decision from discovering it.

Output: draft project profile.

## Phase 4: Produce the knowledge candidate

The knowledge curator creates or proposes a draft that helps a new engineer
understand:

- system purpose and major responsibilities;
- module and folder significance;
- inputs, outputs, contracts, models, data stores, and external interfaces;
- principal runtime, batch, request, or operational flows supported by evidence;
- configuration and environment-variable names without secret values;
- error, retry, recovery, and observability behaviour;
- source and test navigation paths;
- glossary and unresolved questions.

The candidate must carry draft status, source references, and review state. It
must not contain credentials, personal data, production records, or large
source-code reproductions.

Output: source-linked knowledge candidate and relationship summary.

## Phase 5: Verify and hand off

The verifier checks, without converting absence into proof:

- referenced paths exist at the selected revision;
- critical identifiers are spelled consistently;
- links resolve locally where feasible;
- claims are backed by source, schemas, tests, or clearly labelled inference;
- conflicting evidence is visible;
- excluded areas were not incorporated;
- candidate pages are labelled as draft;
- no discovered command was executed without review.

The coordinator returns a compact hand-off containing completed artifacts,
coverage limits, unresolved questions, and the named reviewer action.

## Human gates and stop conditions

Stop before:

1. running any repository-provided command or script that a human has not
   reviewed for inputs, side effects, and target;
2. installing dependencies or changing the selected worktree;
3. connecting to an unapproved external provider or data source;
4. accepting inferred, generated, or graph-derived claims as facts;
5. publishing the candidate or representing it as authoritative.

The final knowledge-acceptance decision belongs to the named reviewer or
subject-matter expert.

## Failure and resumption

On failure, preserve the repository and any existing knowledge unchanged.
Record the selected revision, last completed phase, partial artifacts, complete
failure evidence location, and exact input needed next. Resume only against the
same revision, or explicitly start a new run for a different revision.

## Completion criteria

- The project profile is complete or explicitly marks unresolved fields.
- The inventory and knowledge candidate cite the selected revision.
- Direct evidence and inference are distinct.
- All discovered commands remain unexecuted unless individually reviewed.
- Coverage limits and sensitive exclusions are documented.
- The reviewer has a clear candidate to accept, reject, or revise.


