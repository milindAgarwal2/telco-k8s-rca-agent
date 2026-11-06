# Workflow: Approved Knowledge Maintenance

## Metadata

- Workflow ID: `aide-approved-knowledge-maintenance`
- Trigger: a knowledge-relevant source or configuration change is merged.
- Coordinator: `aide-coordinator`
- Status: reusable protocol; knowledge locations and owners are project-defined.

## Objective

Identify knowledge affected by an immutable merged change, prepare a candidate
delta, obtain subject-matter expert (SME) review, validate approved content,
and rebuild deterministic graph projections or other derived views. Generated
or inferred content never becomes an approved fact merely because automation
produced it.

## Do not use this workflow for

- documenting an unknown repository for the first time;
- editing source code to make documentation easier;
- converting an unmerged proposal into current-state knowledge;
- silently rewriting reviewed specifications after source changes;
- sending repository content to an unapproved model or external service.

Use `aide-repository-onboarding` for first-time discovery and
`aide-approved-change-delivery` when source itself must change.

## Mandatory inputs

1. Immutable merged revision or merge commit and its parent/baseline.
2. Primary knowledge location, secondary/generated locations, and authority
   order.
3. In-scope knowledge types and excluded/sensitive paths.
4. Named knowledge/SME reviewer.
5. Deterministic validation and projection commands, each already reviewed.
6. Approved destinations for candidate changes and derived views.
7. Publication decision owner.

If the source change is not merged or the primary knowledge authority is
unclear, produce an impact report only and stop.

## Roles and methods

| Responsibility | Agent | Skill |
| --- | --- | --- |
| Bind change and coordinate approvals | `aide-coordinator` | `aide-task-planning` when available |
| Trace affected knowledge | `aide-context-analyst` | `aide-context-impact` |
| Draft and rebuild knowledge | `aide-knowledge-curator` | `aide-knowledge-maintenance` |
| Validate claims and references | `aide-verifier` | `aide-test-verification` |

An approved knowledge MCP or graph tool may retrieve existing facts or rebuild
views. It does not replace verification against the selected source revision.
A project-specific wiki generator is optional and must follow its own approved
offline/provider and failure-preservation rules.

## Phase 1: Bind the merged change

The coordinator records:

- repository and immutable before/after revisions;
- merge/change reference and stated intent;
- exact changed-file inventory;
- primary, secondary, generated, and derived knowledge locations;
- reviewer and publication owner;
- approved command and tool boundaries.

Output: knowledge-maintenance run scope.

Stop if the revisions are missing, the change is still mutable, or repository
instructions prohibit generated edits to an in-scope location.

## Phase 2: Detect affected knowledge

The context analyst traces from changed source/configuration to:

- requirements, design, tasks, architecture, interface, data, and runbook pages;
- folder or module specifications;
- identifiers, contracts, environment variables, commands, diagrams, and links;
- primary-to-secondary summaries;
- relationship-map nodes and edges;
- graph entities, claims, embeddings, or indexes derived from reviewed content;
- unresolved questions that the merge answers or invalidates.

Each impact must cite the source change and affected knowledge path. Label an
impact as confirmed, likely, possible, or excluded. Do not edit content during
impact discovery.

Output: affected-knowledge inventory and proposed delta plan.

## Phase 3: Prepare the candidate delta

The knowledge curator updates only candidate/staging content or prepares a
patch for review. The delta must:

- describe current implemented behaviour and intended reviewed behaviour
  without conflating them;
- cite exact source/test/schema paths and revision;
- distinguish direct evidence, inference, historical statement, and unresolved
  question;
- preserve stable identifiers and existing reviewed meaning unless evidence
  requires change;
- explain removed or superseded relationships;
- avoid credentials, personal data, production records, and large code blocks;
- keep generated pages visibly marked as draft.

Do not manually edit protected generated-claim stores or deterministic outputs.
Change their approved input and rebuild them after review.

Output: candidate knowledge delta, impact trace, and open questions.

### Gate A: SME content approval

Stop for the named reviewer to approve, reject, or request changes to the exact
candidate revision. The reviewer decides whether inferences become reviewed
statements. Approval becomes stale after a substantive candidate, source, or
authority-order change.

## Phase 4: Validate approved content

The verifier checks the approved candidate for:

- path, anchor, and cross-reference resolution;
- identifier uniqueness and relationship validity;
- required metadata, owner, review state, and source references;
- consistency with current source, schemas, tests, and reviewed specifications;
- stale statements contradicted by the merge;
- sensitive-data leakage;
- diagram or format syntax using approved deterministic tools;
- explicit labelling of uncertainty and unverified claims.

Subjective completeness is reported for human review rather than converted into
an unreliable automatic pass/fail rule.

Output: validation report and corrections required before derivation.

Stop on contradiction, broken required reference, sensitive content, or failed
deterministic validation.

## Phase 5: Rebuild derived views

After Gate A and validation only, rebuild configured derived artifacts from the
approved primary input. Examples include relationship maps, graph projections,
search indexes, or generated secondary navigation.

The rebuild must be deterministic for the same input and configuration, or its
nondeterministic elements and comparison method must be disclosed. Record:

- exact input revision and command/tool version;
- previous and new counts/checksums where meaningful;
- additions, removals, and rejected records;
- failures and preserved prior state;
- graph/index target and logical namespace without credentials.

If a generator or provider is unavailable, stop safely and preserve the
existing wiki, graph, index, or derived view. Never switch provider or target
automatically.

Output: derived-view build and comparison report.

## Phase 6: Publication hand-off

Prepare the reviewed delta, validation evidence, derived-view report,
unresolved items, and rollback/recovery note for the publication owner.

### Gate B: publication decision

Publishing, merging the knowledge change, replacing a shared graph/index, or
marking pages as reviewed requires the named owner's explicit decision. The
workflow may prepare the change but does not infer publication authority.

## Human gates and stop conditions

Stop before:

1. promoting any inferred or generated statement without SME review;
2. editing protected generated claims or outputs manually;
3. rebuilding from stale, rejected, or unapproved primary content;
4. switching to an unapproved external provider or graph target;
5. replacing an existing knowledge view after a failed build;
6. publication or merge without Gate B.

## Failure and resumption

Preserve existing knowledge and derived views on every failure. Record the
source revision, candidate revision, approved gate state, last successful
output, failed command/tool result, and retry precondition. Resume from the
last valid phase only when upstream inputs are unchanged; otherwise invalidate
later results and re-run affected phases.

## Completion criteria

- Every changed knowledge claim traces to current source or reviewed intent.
- SME approval covers the exact candidate revision.
- Deterministic validation passes or exceptions are explicitly accepted.
- Derived views are rebuilt from approved inputs or remain safely preserved.
- Publication state and unresolved questions are unambiguous.


