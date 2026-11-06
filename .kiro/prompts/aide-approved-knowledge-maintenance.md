# Run AIDE Approved Knowledge Maintenance

Run the reusable workflow `aide-approved-knowledge-maintenance` as the
`aide-coordinator`.

Read first:

1. `.aide/workflows/catalog.json`
2. `.aide/workflows/definitions/maintain-knowledge.md`
3. applicable repository instructions and knowledge-authority guidance

Generated knowledge is a candidate until the named subject-matter expert (SME)
reviews the exact revision. Graphs, indexes, relationship maps, and generated
wikis are derived views, not higher authority than their reviewed inputs.

## Intake

Confirm required agents and skills, then obtain:

- immutable merged revision and baseline/parent;
- primary, secondary, generated, and derived knowledge locations;
- evidence-authority and disagreement rules;
- in-scope knowledge and excluded/sensitive paths;
- SME/knowledge reviewer and publication owner;
- reviewed validation and rebuild commands;
- approved candidate and derived-view destinations.

If the change is not merged or knowledge authority is unclear, produce an
impact report only and stop.

## Execute in phases

1. As `aide-coordinator`, bind the exact source change, knowledge scope,
   reviewer, destinations, and tool boundaries.
2. As `aide-context-analyst`, follow `aide-context-impact`. Trace changed source
   to affected specifications, pages, identifiers, relationships, graph
   entities, and unresolved questions. Do not edit during impact discovery.
3. As `aide-knowledge-curator`, follow `aide-knowledge-maintenance`. Prepare a
   candidate delta with exact source/test/schema evidence. Separate facts,
   inference, history, and unknowns; preserve stable identifiers; do not edit
   protected generated claim stores manually.

## Gate A — SME content approval

Display the immutable source revision, exact candidate revision/paths, changed
claims and relationships, inference list, removed/superseded content,
unresolved questions, and planned deterministic validation/rebuild.

End with `WAITING FOR SME APPROVAL OF THE EXACT KNOWLEDGE DELTA`. Permission to
refresh knowledge is not approval of generated claims.

Only after Gate A:

4. As `aide-verifier`, follow `aide-test-verification`. Validate references,
   identifiers, metadata, evidence, contradictions, sensitive-data exclusion,
   formats, and uncertainty labels using only reviewed commands.
5. As `aide-knowledge-curator`, rebuild configured derived views only from the
   approved primary input. Record input/tool revisions, counts or checksums,
   additions/removals/rejections, and failures. If a generator, graph target,
   or internal provider is unavailable, stop and preserve the existing view;
   never switch providers automatically.

Use project-specific wiki or graph tooling only when already configured and
approved. Never manually modify protected generated claim files.

## Gate B — publication decision

Present the approved delta, validation results, derived-view comparison,
remaining uncertainty, and recovery note. End with
`WAITING FOR KNOWLEDGE PUBLICATION DECISION`.

Do not merge the knowledge change, mark it reviewed, replace a shared graph or
index, or publish it without that decision.

On any failure, preserve current knowledge and derived views. Report source and
candidate revisions, last valid gate, last successful output, complete failure
evidence, and exact retry precondition.


