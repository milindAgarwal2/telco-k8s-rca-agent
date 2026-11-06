---
name: aide-knowledge-maintenance
description: "Use after a reviewed and verified change when asked to update the knowledge-base, folder specifications, OpenWiki inputs, or graph-ingestion material. Produces a focused knowledge delta linked to current evidence and separates observations from established facts."
---

# AIDE knowledge maintenance

Update durable knowledge only after the underlying change and its evidence are
known. Do not turn transient observations into authoritative architecture.

## Procedure

1. Confirm the reviewed change, repository revision, verification evidence, and
   exact knowledge scope authorized by the user.
2. Identify existing affected pages in `knowledge-base/`, folder `SPECS.md`
   files, and `openwiki/`. Treat the reviewed knowledge base as primary and
   generated OpenWiki material as secondary draft context.
3. Compare documented behavior with current source, schemas, tests, and approved
   specifications. Record contradictions for review.
4. Make the smallest coherent documentation update. Preserve stable identifiers
   and links where possible.
5. Label direct evidence, inference, operational observation, proposed state,
   and unresolved questions.
6. For graph ingestion, emit deterministic identifiers, source paths, revision,
   timestamps, entity types, and relationship evidence without writing to the
   graph unless separately requested and authorized.

## Knowledge-delta contract

Report changed pages, claims added or retired, supporting paths, specification
and requirement identifiers, relationship changes, verification evidence,
review status, and remaining questions. Machine-generated pages remain draft
until subject-matter expert review.

## Boundaries

Do not manually edit generated claim stores such as `openwiki/.claims`. Do not
refresh OpenWiki, send content to a provider, ingest Neo4j or Graphiti, or edit
legacy source merely to improve documentation unless the user explicitly asks
for that separate action. Never copy secrets, personal data, production records,
or large source blocks into knowledge artifacts.
