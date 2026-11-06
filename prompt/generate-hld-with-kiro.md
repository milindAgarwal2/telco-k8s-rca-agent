# Kiro Prompt: Generate a Detailed High-Level Design

Use this prompt from the root of the repository being documented.

---

You are documenting the current repository. Create or update a detailed,
evidence-based High-Level Design (HLD) at `knowledge-base/HLD.md`.

## Repository-agnostic rule

This is a reusable prompt. Discover the repository's actual architecture before
choosing document sections, terminology, diagrams, or examples. Do **not**
assume a particular language, framework, product domain, runtime, hardware,
orchestration platform, service style, persistence technology, or topology.
Mention an architecture concern only when current repository source, tests,
configuration, or build/deployment artifacts support it. Omit inapplicable
sections instead of filling them with generic or speculative text.

## Objective

Write a design that lets an engineer new to this repository understand what it
does, the major responsibilities and boundaries, the most important flows,
interfaces, data/resource ownership, configuration, operations, failure modes,
and evidence gaps. Describe the implementation at the current commit, not an
aspirational design or a generic architecture tutorial.

## Mandatory controls

1. Treat current source, schemas, configuration, and focused tests as the
   authority. Read `AGENTS.md` and applicable repository instructions first.
2. Treat `knowledge-base/` and `openwiki/` as draft navigation aids only;
   re-establish technical claims from current repository evidence.
3. Create or update only `knowledge-base/HLD.md`. Do not change application
   source, tests, configuration, build files, generated files, or OpenWiki
   state.
4. Use read-only inspection. Do not run services, destructive scripts,
   workloads, downloads, dependency installation, or documentation generators.
5. Do not use an unapproved external provider or expose secrets, credentials,
   personal data, production records, or large source-code blocks.
6. Never invent a component, runtime flow, interface, datastore, deployment
   guarantee, business rule, security control, failure behavior, or decision.
7. Mark claims as **Direct evidence**, **Inference**,
   **Deployment-dependent**, or **Review required**. Explain every acronym at
   first use and use simple, precise English.
8. Do not propose modernization, refactoring, or code changes unless that is
   explicitly requested.

## Evidence-led investigation

Before writing, establish the commit/date baseline and map the repository:

1. Identify top-level source, test, build, configuration, deployment,
   documentation, example, script, generated, and extension areas.
2. Identify actual entrypoints and consumers: libraries, command-line tools,
   APIs, services, event handlers, jobs, playbooks, plugins, scripts, or other
   repository-supported surfaces.
3. Trace representative end-to-end flows from input/trigger through validation,
   processing, persistence or external interaction where present, output, and
   cleanup. Trace online, batch, asynchronous, event-driven, or operational
   flows only when evidence shows them.
4. Identify architectural boundaries, component ownership, public contracts,
   configuration sources, environment-variable use, extension mechanisms,
   state/resource owners, and failure propagation.
5. Inspect security guidance, logging, metrics, tracing, health checks,
   packaging, build, deployment, and automation artifacts when they exist.
6. Cross-check material claims against focused tests, schemas, or integration
   fixtures where available. Do not turn a fixture or example into a production
   guarantee.

Use targeted searches and symbol-level reads. Follow callers and consumers for
important boundaries rather than producing a file inventory.

## Evidence and linking rules

Near every material claim, cite an exact clickable repository-relative path.
For example, use the label `roles/nginx/tasks/main.yml` and link it to the
verified path relative to the generated document.
Name relevant symbols, resources, configuration keys, or tests where useful.
Prefer path plus symbol over volatile line numbers. Use multiple sources for a
cross-cutting claim. State explicit conditions rather than implying a feature
is universally enabled.

## Required document structure

Use the following outline as a checklist, adapting it to the discovered
repository. Keep only sections that evidence supports; add domain-specific
sections when needed.

### 1. Document control and evidence convention

State title, repository/system name, commit, preparation date, audience,
authority order, draft status, and meanings of the four evidence labels.

### 2. Executive summary

Explain the system's purpose, primary users or consumers, principal execution
model, key design constraints, and the most important evidence gaps. Include a
compact system overview diagram only when it clarifies the architecture.

### 3. Scope, boundaries, and context

Define what the HLD covers, what is out of scope, repository-owned versus
environment-owned behavior, actors, adjacent systems, external dependencies,
and trust boundaries. Include a context table and diagram when supported.

### 4. Architectural drivers and decisions

Document directly evidenced quality attributes and design choices—such as
compatibility, safety, portability, scale, latency, availability, auditability,
or maintainability. For each decision include evidence, rationale (marked as
inference where necessary), consequences, and conditions.

### 5. Logical architecture and repository map

Describe the discovered layers, modules, roles, packages, services, jobs,
playbooks, or other logical components. Give each responsibility, owned state,
key dependencies, stable interfaces, and concrete implementation locations.
Include a component/responsibility matrix and a layered diagram if useful.

### 6. Interfaces and integration boundaries

Catalog each evidenced interface family: caller/consumer, protocol or format,
input, output, validation, authentication or authorization scope if evidenced,
availability condition, implementation anchor, and failure behavior. Include
file, queue, database, message, command, API, library, and human-operational
interfaces only when present.

### 7. Key end-to-end flows

For every important flow supported by evidence, provide a narrative and a
sequence or flow diagram. Cover normal input-to-output behavior, initialization,
scheduled/batch processing, asynchronous/event behavior, cancellation or
rollback, and error handling only where applicable. State triggering condition,
component boundaries, state changes, external effects, output, and cleanup.

### 8. Data, state, and resource architecture

Describe durable stores, files, queues, caches, in-memory state, generated
artifacts, locks, tasks, processes, or hardware resources only when evidenced.
For each, identify owner, format/model, lifecycle, consistency or ordering
rules, retention, concurrency boundaries, and release/cleanup behavior.

### 9. Configuration and environment

Map configuration files, command arguments, environment variables, defaults,
validation, override order, secrets handling, and runtime mutability. State
when configuration is deployment-specific or not found in the repository.

### 10. Extension and customization design

Document registries, plugins, templates, hooks, adapters, customer variants,
feature flags, role variables, or other extension seams only when source or
tests demonstrate them. Explain selection, lifecycle, privilege, compatibility,
and failure isolation.

### 11. Security architecture

Use repository security guidance and evidence to document trust boundaries,
identity/access controls, input validation, secret handling, dependency or
artifact supply-chain controls, data sensitivity, and residual risks. State
explicitly when the repository cannot prove a deployment control.

### 12. Reliability, failure handling, and recovery

Provide a failure/control matrix: trigger, detection, propagation, user or
operator impact, cleanup, recovery owner, observability, and guarantee not
provided. Distinguish local validation failures from process, dependency,
network, data, or environment failures when relevant.

### 13. Observability and operations

Map logs, events, metrics, traces, health/readiness checks, audit records,
administrative commands, runbooks, deployment artifacts, startup/shutdown, and
capacity/performance evidence where they exist. Avoid inventing operational
procedures or performance figures.

### 14. Build, packaging, deployment, and verification

Explain repository-supported build/package/deployment shapes and their
constraints. Map unit, integration, contract, end-to-end, lint, static, and
environment-specific verification to the architectural risks they cover.

### 15. Constraints, traceability, glossary, and open questions

Separate direct constraints from inferred ones. Add a source traceability
matrix for major conclusions, define repository/domain terms, and group
unresolved questions by owner or area. Do not present review questions as
requirements.

## Diagrams and depth

Use Mermaid only where it materially improves understanding. At minimum,
include a context view, component view, and representative flow when the
repository contains enough evidence for each. Add topology, state, lifecycle,
data ownership, or trust-boundary views only when applicable. Follow every
diagram with a short interpretation. Use tables for interfaces, decisions,
configuration, risks, and traceability.

Be as detailed as evidence supports. Prefer a focused, complete document over
an arbitrary word count, copied code, repeated claims, or inapplicable
technology sections.

## Validation before completion

1. Ensure `knowledge-base/HLD.md` exists and is non-empty.
2. Verify relative Markdown links, heading hierarchy, tables, and Mermaid/code
   fences are valid and balanced.
3. Search for TODO/TBD placeholders, unsupported examples, and sensitive data.
4. Confirm every major section is evidence-backed or explicitly marked for
   review, and that no source/tests were changed.
5. Inspect repository status and report the artifact changed by this task.

## Final response

Report the created path, approximate line/word counts, major coverage,
validation results (including link count and broken-link count), confirmation
that no application source or tests changed, and material evidence gaps. Do
not paste the entire HLD into chat.
