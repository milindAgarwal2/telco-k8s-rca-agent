---
name: aide-spec-authoring
description: "Use when asked to create, refine, or review requirements or a Kiro specification from a Jira item, user request, or approved context. Produces risk-proportionate requirements with EARS acceptance criteria, exclusions, risks, evidence, and measurable success conditions."
---

# AIDE specification authoring

Translate an approved request into testable intent without inventing current
behavior or prematurely designing the implementation.

## Evidence order

Use source and schemas, tests, reviewed specifications, generated drafts, then
relationship maps. Reviewed specifications describe intended behavior; source
and tests show current implementation and verification. Surface disagreements
instead of silently choosing one.

## Procedure

1. Identify the request source, stakeholders, business outcome, scope, and
   exclusions. Record the repository revision used for current-state evidence.
2. Consult `knowledge-base/` first, `openwiki/` second, folder `SPECS.md` files,
   and relevant source and tests. Cite exact paths.
3. Separate current facts, requested intent, assumptions, and unknowns.
4. Choose a lightweight specification for isolated low-risk behavior or a full
   specification when contracts, operations, security, data, or multiple
   components are involved.
5. Write acceptance criteria using the appropriate Easy Approach to
   Requirements Syntax (EARS) form:
   - ubiquitous: `The system shall ...`;
   - event-driven: `When <event>, the system shall ...`;
   - state-driven: `While <state>, the system shall ...`;
   - unwanted behavior: `If <condition>, then the system shall ...`;
   - optional feature: `Where <feature>, the system shall ...`.
6. Give each requirement a stable unique identifier and make every acceptance
   criterion observable. Include negative and failure behavior where relevant.
7. Define measurable success, constraints, compatibility, risks, and questions.

## Output contract

Write only the specification artifacts requested by the active workflow. Reuse
the existing Kiro spec layout and templates if present. A complete requirements
document normally includes purpose, evidence, glossary, scope, exclusions,
requirements, EARS acceptance criteria, constraints, risks, success measures,
traceability, assumptions, and unresolved questions.

For operational requests, name the authorized target, expected action, side
effects, success signal, failure signal, and rollback expectation. Do not embed
credentials or production records.

## Boundaries

Do not implement code, approve the specification, or convert unknowns into
requirements. Mark generated content as draft pending subject-matter expert
review.
