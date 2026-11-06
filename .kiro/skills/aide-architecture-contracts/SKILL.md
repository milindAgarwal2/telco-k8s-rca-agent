---
name: aide-architecture-contracts
description: "Use when asked to create or update a high-level design, low-level design, C4 view, interface contract, configuration contract, data-flow description, or cross-service architecture analysis. Keeps current, proposed, inferred, and unknown states distinct."
---

# AIDE architecture and contracts

Describe the architecture needed to decide and verify a change. Prefer focused
updates to a broad rewrite.

## Procedure

1. Confirm whether the output is current-state documentation, a proposed
   design, or both. Never merge those states into one unlabeled diagram.
2. Read applicable instructions, approved requirements, relevant
   `knowledge-base/` material, the secondary `openwiki/` index, folder
   `SPECS.md` files, and primary source evidence.
3. Identify system context, containers or deployable units, components,
   runtime responsibilities, trust boundaries, and ownership only where
   supported.
4. Trace interfaces, request and event flows, schemas, persistence,
   configuration, environment variables, failure paths, retries, timeouts,
   idempotency, and observability.
5. Define each changed contract with producer, consumer, input, output,
   invariants, errors, compatibility, versioning, and verification evidence.
6. For cross-service changes, show the end-to-end sequence and the local change
   required in each repository or deployable unit.
7. Label direct evidence, design decisions, inference, and unknowns.

## Diagram rules

Use Mermaid only when it clarifies structure or sequence. Give nodes stable,
human-readable names and follow each diagram with text that explains the
boundary, evidence, and unresolved assumptions. Suitable views include C4-like
context and container views, component diagrams, sequence diagrams, data-flow
diagrams, and deployment views.

## Output contract

Produce only the requested HLD, LLD, diagram, or contract updates. Include:

- purpose, scope, exclusions, and requirements traced by identifier;
- current-state evidence and proposed-state decisions in separate sections;
- components, interfaces, data and configuration models;
- normal, degraded, and failure flows;
- security and operational constraints relevant to the change;
- compatibility, rollout, rollback, and verification considerations;
- alternatives, decisions, assumptions, and unresolved questions.

Do not claim a future design already exists. Do not expose secrets or reproduce
large source blocks.
