---
name: aide-context-impact
description: "Use when asked what a proposed change affects, which context is relevant, or which consumers and contracts must be checked. Produces a minimal evidence-backed context pack with sources, revisions, impact paths, assumptions, and questions."
---

# AIDE context and impact

Gather only the context needed to assess the proposed change. More context is
not automatically better; relevance and traceability are the objective.

## Procedure

1. Restate the change hypothesis, in-scope behavior, and exclusions.
2. Read applicable workspace instructions and the nearest existing
   specifications.
3. Trace the affected component outward through imports, calls, contracts,
   configuration, environment variables, persistence, jobs, deployment
   manifests, tests, and operational consumers.
4. Use `knowledge-base/` as reviewed architectural context and `openwiki/` as a
   secondary index. Confirm consequential claims in source, schemas, and tests.
5. Query Neo4j or Graphiti only when the integration is already configured,
   approved for this repository, and relevant. Treat retrieved relationships
   as discovery leads until verified against the cited repository revision.
6. Stop expanding when another hop cannot change scope, design, verification,
   rollout, or rollback decisions.

## Context-pack contract

Return:

- change statement, scope, exclusions, and repository revision;
- affected components and why each is relevant;
- upstream producers and downstream consumers;
- contracts, models, configuration, environment variables, and data paths;
- tests and operational checks that provide verification evidence;
- direct evidence with paths, separate from inference;
- source or graph timestamps when available;
- assumptions, contradictions, and focused unanswered questions.

Use an impact chain when relationships matter:

```text
requested behavior -> changed contract -> consumers -> verification -> rollout
```

## Boundaries

Do not upload repository content, write to a knowledge graph, or refresh an
index during impact analysis unless explicitly requested. Never treat semantic
similarity or an old graph edge as proof of current behavior.
