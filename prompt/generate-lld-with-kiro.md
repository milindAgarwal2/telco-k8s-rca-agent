# Kiro Prompt: Generate a Detailed Low-Level Design

Use this prompt from the root of the repository being documented.

---

You are documenting the current repository. Create or update a detailed,
evidence-based Low-Level Design (LLD) at `knowledge-base/LLD.md`.

## Repository-agnostic rule

This is a reusable prompt. First discover the repository's languages,
execution model, domain, and real implementation boundaries. Do **not** impose
a particular programming language, framework, service style, deployment model,
hardware model, persistence technology, or distributed-compute structure.
Include a topic only when it is evidenced by current repository source, tests,
schemas, configuration, build, or deployment artifacts. Omit inapplicable
topics rather than writing generic filler.

## Objective

Create an implementation-level design that enables a new engineer to trace,
debug, test, and safely change the existing system. Explain concrete modules,
types, functions, tasks, processes, resources, contracts, state transitions,
algorithms, error behavior, concurrency, configuration, and verification only
to the level supported by evidence. Describe the current commit—not a proposed
future solution.

## Mandatory controls

1. Read `AGENTS.md` and applicable repository instructions. Current source,
   schemas, configuration, and focused tests are authoritative.
2. Use the HLD, OpenWiki, and existing knowledge-base files only as navigation
   aids; re-establish each low-level statement from current evidence.
3. Create or update only `knowledge-base/LLD.md`. Do not modify source, tests,
   build files, configuration, generated content, the HLD, or OpenWiki state.
4. Use read-only inspection. Do not start services, execute destructive or
   workload commands, download dependencies, install packages, or generate
   documentation through another tool.
5. Do not send repository content to an unapproved external provider or copy
   secrets, credentials, personal data, production records, or large code
   blocks.
6. Never invent a field, call, state transition, queue, message, file, table,
   resource rule, validation, exception path, or cleanup guarantee.
7. Label findings as **Direct evidence**, **Inference**,
   **Deployment-dependent**, or **Review required**. Explain acronyms at first
   use; preserve exact identifiers and use simple English.
8. Do not propose refactoring, modernization, or code changes unless explicitly
   requested.

## Evidence-led investigation

Complete a targeted, method-level investigation before drafting:

1. Record commit, date, repository status, relevant instructions, and the
   source/test/configuration/build areas.
2. Identify real public and operational entrypoints: APIs, commands, jobs,
   event handlers, playbooks, scripts, libraries, hooks, plugins, or other
   supported invocation surfaces.
3. For each critical flow, trace caller → validation/normalization → internal
   representation → processing/side effect → response/output → cleanup.
4. Map important interfaces and data representations. For each, record fields
   or parameters, type/format, defaults, producer, consumer, mutability,
   serialization, lifecycle, identifier/correlation rules, and compatibility
   constraints where evidence makes them known.
5. Trace initialization, steady-state work, shutdown, error, retry, rollback,
   cancellation, and recovery paths when they exist.
6. Identify processes, threads, event-loop tasks, queues, locks, files,
   sockets, databases, caches, external services, generated artifacts, and
   hardware resources only when evidence shows them. Establish their owner,
   lifetime, concurrency boundary, and cleanup.
7. Locate focused tests for critical invariants. Inspect implementation and
   call sites, not just declarations, comments, or fixture data.

Use targeted symbol searches and reads. Follow relevant callers and consumers;
do not create a symbol dump or exhaustively read unrelated large files.

## Evidence and linking rules

Put exact clickable relative source links beside material claims. For example,
use the label `tasks/main.yml` and link it to the verified path relative to the
generated document. Name the relevant module, class,
function, play, task, handler, schema, resource, configuration key, or test.
Describe preconditions, input, mutation/side effect, output, failure, and
cleanup for each important behavior. Mark ordering or positional dependencies
explicitly. Prefer path plus symbol over volatile line numbers.

## Required document structure

Adapt this outline to the evidence. Retain only applicable sections and add
repository-specific sections where they make the implementation clearer.

### 1. Document control, scope, and evidence convention

State system, commit, date, audience, relationship to the HLD, authority
order, draft/review status, scope, non-goals, and the evidence labels.

### 2. Implementation map and ownership

Provide a module/package/directory map, dependency diagram, responsibility
matrix, stable interfaces versus implementations, factories/registries where
present, and owners of major state and lifecycle decisions.

### 3. Concrete contracts and data models

Create field- or parameter-level tables for important request, response,
configuration, event, file, schema, database, message, or internal objects.
Include representation transformations, validation, defaults, mutability,
serialization, ownership, and compatibility risks.

### 4. Initialization and lifecycle

Trace initialization from each important entrypoint through configuration,
dependency construction, resource acquisition, readiness, normal operation,
shutdown, and cleanup. For each phase provide caller, operation, state created,
dependencies, possible failure, and completion condition.

### 5. Core processing algorithms and state machines

For each central algorithm or workflow, give an evidence-backed narrative,
method-level pseudocode when useful, state diagram, transition table,
preconditions, inputs, state mutation, outputs, and terminal/error behavior.
Do not invent equations, state names, or policies.

### 6. End-to-end execution sequences

Provide detailed sequence diagrams for representative successful and failure
flows. Include synchronous, asynchronous, scheduled, batch, event-driven,
interactive, or operational flows only when they exist. Name concrete method
and component boundaries.

### 7. Concurrency, communication, and ordering

Document threads, processes, tasks, queues, locks, futures, sockets, message
formats, callbacks, synchronization, ordering, backpressure, liveness, and
shutdown ownership when applicable. Explain deadlock, retry, and partial
failure safeguards only when evidenced.

### 8. Persistence, files, caches, and resource lifetime

For every material durable or bounded resource, document owner, allocation or
creation, format/layout, lifecycle, retention, concurrent access, cleanup,
failure cleanup, and capacity/timeout bounds. Include memory/device or native
resource detail only when it exists in the repository.

### 9. Configuration and extension implementation

Map command arguments, configuration files, variables, environment values,
defaults, validation, precedence, runtime mutability, and consumers. Describe
plugins, templates, adapters, providers, roles, feature flags, hooks, or other
extension seams only if demonstrated by current evidence.

### 10. Boundary-specific implementation

For each supported API, command, job, script, external service, file exchange,
database, queue, or infrastructure boundary, explain protocol/format,
authentication/authorization scope if evidenced, request/output mapping,
timeouts/retries, error conversion, compatibility, and test anchors.

### 11. Failure handling, recovery, and security implementation

Separate validation, business, dependency, process, data, configuration,
permission, and deployment failures where applicable. Provide a matrix with
detection, propagation, observable result, state mutation, cleanup, recovery
owner, and guarantees not provided. Document implemented security controls and
residual risks without assuming deployment controls that source cannot prove.

### 12. Observability, build, and verification traceability

Map logs, metrics, events, traces, health checks, audit data, build/package
steps, generated artifacts, and test suites to exact producers/consumers.
Create a matrix mapping important invariants and flows to source, focused test,
test level, failure guarded against, environment requirement, and evidence gap.

### 13. Change-impact review aids

Add concise behavioral matrices and checklists that are actually applicable:
contract compatibility, state transitions, resource lifecycle, error mapping,
configuration precedence, concurrency ordering, and extension behavior.

### 14. Glossary, unresolved questions, and review record

Define domain terms, identify gaps by technical owner/area, and state what an
SME must confirm. Do not translate absence of evidence into a requirement.

## Diagrams and depth

Use Mermaid or compact text diagrams when they clarify relationships. At a
minimum include an implementation/dependency view, a representative lifecycle
or sequence, and a state/resource view when evidence supports them. Add
process/topology, concurrency, data-transformation, protocol, or error-flow
views only when applicable. Follow every diagram with an interpretation.

Be very detailed where the codebase supports it, but never inflate the document
with copied code, generic technology sections, or repeated facts. A smaller
repository may legitimately need fewer sections than a multi-component system.

## Validation before completion

1. Ensure `knowledge-base/LLD.md` exists and is non-empty **before** reporting
   completion.
2. Verify relative links, heading hierarchy, tables, and Mermaid/code fences.
3. Search for TODO/TBD placeholders, unsupported examples, conflict markers,
   and sensitive content.
4. Check identifiers against source spelling and pseudocode against actual
   control flow.
5. Confirm no source, tests, HLD, build, or configuration files were changed;
   inspect repository status and report the LLD artifact.

## Final response

Report the created path, approximate line/word counts, coverage, diagram and
source-link counts, validation results, confirmation that application source
and tests were not changed, and unresolved evidence gaps. Do not paste the
entire LLD into chat.
