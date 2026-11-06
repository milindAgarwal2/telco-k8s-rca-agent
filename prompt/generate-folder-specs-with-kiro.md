# Kiro Prompt: Generate Repository-Wide Folder Specifications

Copy the prompt below into Kiro while the repository root is the active
workspace.

---

You are working in the current repository. Establish a source-grounded,
repository-wide specification hierarchy for spec-driven development by
creating or updating a file named `SPECS.md` in the repository root and in
every in-scope project-owned subfolder.

## Objective

Create a navigable set of folder-level specifications that lets an engineer
unfamiliar with the repository determine, for every folder:

- why the folder exists and why it is significant;
- which responsibilities it owns and does not own;
- what enters and leaves the folder at runtime, build time, test time, or
  documentation time;
- which interfaces, data models, protocols, schemas, file formats, registry
  keys, command-line options, and lifecycle rules form its contracts;
- which other folders produce its inputs or consume its outputs;
- how errors, invalid state, cleanup, cancellation, retry, and propagation are
  handled;
- which environment variables and other configuration mechanisms affect it;
- which memory, storage, process, thread, task, device, queue, cache, file, and
  network resources it owns or references;
- how its important control, data, build, or documentation flow fits into the
  rest of the repository;
- which tests or other evidence verify its behavior;
- which conclusions are direct evidence, bounded static-analysis results,
  inferences, deployment-dependent behavior, or unresolved questions.

The result is a specification baseline for the repository as it exists at the
current commit. It is not a future architecture proposal, modernization plan,
or substitute for source code and tests.

## Required deliverables

1. Create or update the root `SPECS.md` as the repository integration
   specification and master index.
2. Create or update one `SPECS.md` in every in-scope project-owned subfolder.
3. Give each specification a deterministic, path-derived specification
   identifier and folder-specific acceptance-scenario identifiers.
4. Link every child specification to its parent specification.
5. Link the root specification to every subfolder specification in a complete
   repository specification index.
6. Use relative Markdown links for repository files and specifications so the
   hierarchy remains usable from a local checkout.

Do not stop after producing a representative sample. Completion means exact
coverage of every directory selected by the scope rules below.

## Non-negotiable constraints

1. Read and obey the repository's `AGENTS.md` and all applicable nested or
   domain-specific instructions before modifying anything.
2. Treat source code, tests, schemas, build definitions, configuration, and
   maintained documentation as authoritative evidence.
3. Do not use generated OpenWiki pages as source material, evidence, or
   context. Do not run OpenWiki and do not modify `openwiki/`, especially
   `openwiki/.claims/`.
4. Do not modify application source, tests, build definitions, configuration,
   diagrams, artifacts, or existing non-`SPECS.md` documentation. The only
   persistent changes from this task must be `SPECS.md` files.
5. Preserve all unrelated and pre-existing workspace changes. Never reset,
   revert, delete, format, or overwrite them.
6. Use read-only inspection of repository content. Do not start servers, run
   model inference, download models, install dependencies, or invoke external
   documentation generators.
7. Do not send repository content to an unapproved external provider. Work
   entirely in the approved workspace.
8. Never invent an interface, method call, model, field, table, file, queue,
   transaction, registry entry, state transition, environment variable,
   exception, retry policy, cleanup guarantee, runtime flow, or test result.
9. Clearly distinguish direct evidence from inference. Label uncertainty,
   bounded-scan limitations, deployment-specific behavior, and unresolved
   findings.
10. Do not reproduce secrets, credentials, personal data, production records,
    proprietary payloads, or large source-code blocks.
11. Do not recommend modernization, refactoring, dependency replacement, or
    code changes unless the request is explicitly amended to include them.
12. Explain an acronym the first time it appears in a specification, unless it
    is an exact source identifier whose spelling must be preserved.
13. Use simple, precise English and exact repository terminology.
14. Mark every generated or refreshed specification as a draft until a
    maintainer or subject-matter expert reviews it.
15. A folder is not exempt merely because it contains documentation, tests,
    configuration, build automation, diagrams, prompts, skills, examples,
    benchmarks, fixtures, data files, or specifications instead of runtime
    source code.

## Checkpointed execution and AIDE overlay boundary

This prompt is run by an automated, resumable post-installation workflow.
Complete the safe work without asking the operator to choose among formatting,
refresh, coverage, or preservation strategies. Ask a question only when a
credential, authorization, missing external input, or destructive action makes
safe progress impossible. Record ordinary ambiguity under unknowns and review
items instead of pausing.

Before deriving specification scope, check for
`.aide/managed-files.json`. When it exists:

1. Parse its top-level `files`, `control_files`, and `settings` path keys.
2. Subtract those exact AIDE-managed paths from tracked and non-ignored
   untracked inventory before deriving directories.
3. Exclude `.aide/`, `.kiro/`, and `openwiki/` as AIDE support or generated
   boundaries. Never generate, refresh, count, index, or validate their
   `SPECS.md` files as target-project specifications.
4. Preserve AIDE-managed files unchanged. Their presence does not prove that
   their parent directory belongs to the target application's architecture.
5. Include a directory shared with AIDE only when at least one remaining
   project-owned file exists after the managed paths are subtracted.

The managed receipt is an ownership boundary, not technical evidence about the
target application. Do not describe installed agents, skills, hooks, MCP
servers, prompts, or baseline runtime code as application components unless a
separate project-owned file proves that relationship.

## Scope-selection rules

Build the scope deterministically before writing files.

### Include

Include:

- the repository root;
- every directory represented by at least one project-owned file returned by
  version-control inventory;
- every directory represented by a non-ignored, project-owned workspace file;
- all ancestors needed to connect those directories to the root;
- source, test, native, build, packaging, deployment, documentation, example,
  benchmark, workflow, configuration, fixture, artifact, diagram, prompt,
  skill, and policy directories;
- directories whose only direct file will be `SPECS.md` when they are required
  as an ancestor of an included project directory.

Use version-control-aware inventory as the primary boundary. A suitable Git
inventory is the union of:

- `git ls-files`; and
- `git ls-files --others --exclude-standard`.

Remove existing `SPECS.md` paths from the inventory before deriving expected
directories. Otherwise a stale specification can make an obsolete directory
appear to remain in scope.

### Exclude

Exclude:

- `.git/` and other version-control internals;
- AIDE-managed paths identified by `.aide/managed-files.json`;
- `.aide/`, `.kiro/`, `openwiki/`, and their generated or support content;
- ignored virtual environments, dependency installations, caches, coverage
  output, temporary directories, editor metadata, downloaded models, logs,
  core dumps, and generated build output;
- ignored `node_modules/`, `build/`, `dist/`, and `target/` directories when
  they are generated outputs rather than maintained repository content;
- vendored or nested repositories that are not maintained as part of this
  repository;
- directories that exist only because of transient tooling and contain no
  tracked or non-ignored project-owned file.

Do not exclude a directory solely because its name resembles a build or target
directory. If version control proves that it contains maintained project
content, include it unless repository instructions explicitly say otherwise.

### Scope record

Before generation, calculate and retain:

- tracked-file count;
- non-ignored untracked-file count;
- expected directory count, including the root;
- existing `SPECS.md` count;
- counts grouped by top-level directory;
- explicit exclusions and the reason for each exclusion class.

Use this record during final validation. Do not estimate coverage by eye.

## Evidence-gathering workflow

Perform a bounded, repeatable scan for every in-scope directory. Prefer fast
repository search and targeted reads over dumping large files.

### 1. Classify the folder

Determine whether the folder primarily owns one or more of these roles:

- production runtime;
- public or internal interface;
- data model, schema, or protocol;
- native or accelerator implementation;
- build, packaging, or generated binding;
- deployment or operations;
- test, fixture, evaluation, or benchmark;
- example or integration demonstration;
- documentation or static asset;
- workflow, policy, prompt, skill, or agent guidance;
- configuration or dependency declaration.

Derive the role from filenames, declarations, imports, build references,
tests, and maintained documentation. Do not infer the role from the folder
name alone when direct evidence is available.

### 2. Inventory direct contents

For the folder itself, not its entire subtree, record:

- direct files and immediate child folders;
- artifact type and byte size;
- language or format;
- executable entrypoints;
- tests, fixtures, schemas, diagrams, binaries, generated files, and
  documentation;
- important declared symbols, capped to keep the document usable.

When a folder contains many files, include a complete direct-file inventory
when practical. If a cap is necessary, state the cap and provide totals so the
reader knows the evidence is bounded.

### 3. Discover contracts and models

Inspect applicable declarations such as:

- classes, functions, protocols, abstract interfaces, enumerations, data
  classes, typed dictionaries, structures, traits, and public constants;
- request, response, configuration, event, message, tensor, cache, and state
  representations;
- command-line interfaces and options;
- Hypertext Transfer Protocol (HTTP), Remote Procedure Call (RPC), socket,
  queue, file, serialization, and database formats;
- registries, plugin hooks, entry points, feature gates, build targets, and
  extension interfaces;
- schema, configuration, and documentation contracts;
- test fixtures, parameter sets, expected outcomes, and skip/marker contracts.

Capture public and compatibility-sensitive names exactly. Link each listed
symbol or contract to the direct source file that proves it.

### 4. Discover interaction points

Identify direct relationships using evidence appropriate to each language or
artifact:

- Python imports, relative imports, registrations, callbacks, and entry points;
- C and C++ includes, registrations, bindings, and build targets;
- Rust modules, `use` statements, crates, traits, foreign-function interfaces,
  and bindings;
- CMake, shell, Docker, workflow, and packaging references;
- configuration references and generated-code inputs/outputs;
- documentation links and artifact consumers;
- tests importing or exercising the folder;
- inbound consumers found by a repository-wide dependency scan.

Separate:

- parent containment;
- immediate child ownership;
- outbound dependencies;
- inbound consumers;
- runtime-only dynamic relationships that a static scan cannot prove.

If dependency discovery is heuristic, state that clearly. Do not turn a text
match into a guaranteed runtime call relationship.

### 5. Inspect failure behavior

Record direct evidence for:

- raised, returned, asserted, logged, or translated errors;
- exception catches and propagation;
- validation and invalid-input behavior;
- result/status/error types;
- cancellation, timeout, retry, fallback, or fail-fast behavior;
- cleanup across success, cancellation, abort, and failure;
- test assertions and expected failures.

Distinguish a source assertion used as an invariant from caller-facing input
validation. If no direct failure mechanism is found, say so instead of
inventing one.

### 6. Inspect environment and configuration

Search direct files for environment-variable access and configuration inputs,
including centralized environment modules, `getenv`-style calls, process
environment mappings, command-line options, configuration objects, workflow
variables, build variables, and test fixtures.

For each directly accessed environment variable, document when evidence
supports it:

- exact name;
- purpose;
- parser and type;
- default;
- validation;
- consumer;
- security or operational sensitivity;
- relevant tests.

Do not attribute an environment variable to a folder merely because a
transitive dependency uses it. When no direct access is found, state that
configuration can still arrive through arguments, typed objects, build
settings, fixtures, or parent components.

### 7. Build the storage and memory/resource map

Use “memory map” broadly and precisely. Describe relevant resources such as:

- host memory, device memory, tensors, buffers, views, and copies;
- caches, blocks, pages, pools, reference counts, and eviction boundaries;
- files, memory maps, database state, object stores, and serialized artifacts;
- processes, threads, event loops, asynchronous tasks, futures, queues, locks,
  sockets, streams, and inter-process channels;
- models, tokenizers, compiled graphs, native handles, and dynamically loaded
  libraries;
- test fixtures, temporary resources, benchmark datasets, and build artifacts;
- documentation assets and generated deliverables.

For each relevant resource, state the owner, address space or storage location,
lifetime, sharing/copying behavior, concurrency boundary, and normal or
exceptional release mechanism when direct evidence supports those details.
Do not claim deterministic release where the implementation does not prove it.

### 8. Locate verification evidence

Find the cheapest relevant verification boundary:

- unit test;
- component test;
- integration test;
- end-to-end test;
- native/kernel correctness test;
- distributed or device test;
- schema or build validation;
- documentation link/render validation;
- workflow or packaging check;
- benchmark or evaluation when behavior is performance- or model-sensitive.

Link existing tests when a direct relationship can be established. Never claim
that a test passed unless it was actually run. This documentation task should
normally inspect tests without executing expensive suites.

## Required structure for every `SPECS.md`

Use the following structure consistently. Content must remain folder-specific;
do not fill sections with identical generic prose when direct evidence exists.
A section may explicitly say that it is not applicable or that no direct
evidence was found.

### Document title

Use:

`# <repository-relative folder> Folder Specification`

For the root, use:

`# Repository Root Folder Specification`

### Specification metadata

Provide a table containing:

- deterministic specification identifier;
- repository-relative folder;
- concise role;
- current commit identifier;
- generation or refresh date;
- status: draft until maintainer review;
- relative link to the parent specification, except at the root.

Add an authority notice stating that source, tests, schemas, and build
definitions remain authoritative.

### 1. Intent and significance

Explain:

- why the folder exists;
- its owned responsibilities;
- why it matters to the repository;
- whether it is a leaf or aggregation boundary;
- how child specifications refine its contract.

### 2. Scope and contents

Include direct file count, immediate child count, direct artifact size,
content-type summary, important entrypoints, and direct inventory notes.

### 3. Inputs

Describe applicable runtime, build, test, documentation, configuration, file,
network, model, and parent-component inputs. Link direct producer folders.

### 4. Outputs

Describe applicable return values, messages, state mutations, files, binaries,
registrations, metrics, logs, documentation, build artifacts, and error
signals. Link direct consumers when supported.

### 5. Contracts and models

Use these subsections:

- `### 5.1 Behavioral contracts`
- `### 5.2 Declared models and callable surface`
- `### 5.3 Required invariants`

Provide an evidence-linked symbol/model table when the folder declares a
meaningful surface. Describe compatibility-sensitive formats and lifecycle
ordering. Avoid pretending internal helper names are public contracts.

### 6. Interaction points

Provide an evidence-based table with direction, linked folder, and interaction
type. Cover parent, children, outbound dependencies, and inbound consumers as
applicable. State static-scan limitations.

### 7. Exception and error handling

Provide an evidence table for direct mechanisms and then explain propagation,
diagnostic preservation, cleanup, cancellation, rollback, or partial-mutation
semantics only where proven. Record unresolved behavior when it matters.

### 8. Environment variables and configuration

List direct environment-variable evidence and other configuration channels.
When none is found, say so explicitly and describe only proven configuration
entry points.

### 9. Storage, memory, and resource map

Provide a resource table covering relevant owner, lifetime, and release or
bound. Address host/device, persistent/transient, local/distributed, and
success/failure lifetimes where applicable.

### 10. Interaction diagram

Include exactly one syntactically valid Mermaid diagram. Choose the smallest
useful type for the folder:

- flowchart for producer/consumer boundaries;
- sequence diagram for ordered interaction;
- state diagram for lifecycle transitions;
- graph for build, dependency, or documentation relationships.

Use only evidence-backed node and edge labels. A minimal diagram is preferable
to an invented detailed flow.

### 11. Cross-cutting design considerations

Discuss only applicable concerns such as concurrency, security, compatibility,
performance, observability, portability, generated code, testability,
deployment, data integrity, or documentation maintenance.

### 12. Spec-driven development protocol

Require future work in the folder to:

1. update the specification with the intended contract delta;
2. identify affected parent, child, producer, and consumer specifications;
3. define the smallest evidence or test that proves the behavior;
4. implement without silently widening scope;
5. run proportionate validation;
6. reconcile the specification with the final implementation.

Add at least four folder-specific acceptance scenarios with stable identifiers
covering:

- intended valid behavior;
- invalid input or dependency failure;
- compatibility or lifecycle preservation;
- verification of the changed contract.

Use Given/When/Then semantics even if written as compact prose. Where the
folder is documentation or build-only, adapt the scenarios to its actual
artifact contract.

### 13. Verification strategy

Identify the cheapest appropriate validation and link relevant existing tests,
checks, or consumers when evidence supports the connection. Do not record
unexecuted checks as successful.

### 14. Evidence inventory

List direct files with relative links, artifact types, and byte sizes. State
the total if the table is capped.

### 15. Repository specification index

Include this section only in the root `SPECS.md`. List every in-scope subfolder
exactly once with:

- repository-relative folder;
- concise role;
- relative link to that folder's `SPECS.md`.

Sort the index deterministically by repository-relative path.

### 15/16. Unknowns and review items

Record bounded-scan limitations, dynamic relationships, deployment-specific
behavior, evidence gaps, and maintainer decisions still required. Do not use
unknowns as a place for generic filler or unsolicited improvement ideas.

For a non-root specification, number this section `15`. For the root
specification, place it after the repository index and number it `16`.

## Quality rules

1. Every technical claim must be supported by direct repository evidence or
   explicitly labeled as inference.
2. Prefer exact relative source paths over unlinked prose.
3. A source declaration proves existence, not necessarily runtime use.
4. A test proves only the behavior it actually asserts.
5. An import proves a dependency edge, not the complete call sequence.
6. A configuration declaration does not prove a deployment uses the option.
7. Absence in a bounded scan means “not identified,” not “does not exist.”
8. Avoid duplicated boilerplate. Shared governance wording may be consistent,
   but intent, inputs, outputs, symbols, interactions, errors, environment
   access, resources, diagrams, verification, and evidence inventories must be
   grounded in each folder.
9. Keep large symbol lists and dependency lists usable through deterministic
   caps. State totals and caps.
10. Use relative links with path escaping that works for spaces and special
    characters.
11. Keep heading levels, tables, and diagram fences consistent.
12. Do not embed large code excerpts. Use identifiers, concise pseudocode only
    when needed, and source links.

## Existing-specification refresh policy

If `SPECS.md` files already exist:

1. Inspect them before writing.
2. Preserve explicit maintainer-authored decisions, normative constraints,
   reviewed status, and unresolved questions unless current evidence proves
   they are obsolete.
3. Reconcile metadata, contents, evidence links, dependencies, symbols,
   environment variables, resource maps, and index coverage with the current
   workspace.
4. Do not downgrade a reviewed specification to generated boilerplate.
5. Mark changed machine-generated sections as draft pending review.
6. Report material conflicts between an existing specification and source/test
   evidence instead of silently choosing one.

If the existing files are clearly generated drafts with no maintainer edits,
they may be deterministically refreshed in full.

Do not pause to ask how to handle a project-owned existing specification. Use
this deterministic policy:

1. Preserve an explicitly reviewed specification and extend it in place only
   where required for current coverage and structure.
2. Refresh an explicitly generated draft in place while preserving still-valid
   project decisions and review items.
3. When provenance is ambiguous, choose preservation: retain the existing prose
   and add the smallest missing sections, metadata, links, and evidence needed
   for compliance.
4. Report material evidence conflicts and preserved nonstandard structure as
   review items, but continue every safe generation and validation step.
5. Never treat an AIDE-managed specification excluded by the ownership boundary
   as an existing project specification.

## Safe generation workflow

1. Inventory the repository and calculate the exact expected directory set.
2. Inspect representative folders from production runtime, tests, native code,
   build/workflows, documentation, and workspace guidance.
3. Define one deterministic document model and path/link strategy.
4. Perform the bounded evidence scan.
5. Generate the root and folder specifications.
6. If temporary local tooling is needed for the mechanical write, keep it at
   the repository root, do not add it to the deliverables, and remove it after
   successful generation.
7. Do not delete existing specifications as a recovery shortcut. If generation
   fails, preserve completed valid files, identify incomplete files, and repair
   only the affected scope.
8. Recompute the directory inventory after generation while excluding
   `SPECS.md` from the source set.
9. Run every validation gate below.
10. Inspect representative final specifications for actual content quality,
    not just structural compliance.

## Mandatory validation gates

Do not report completion until all applicable gates pass.

### Coverage

- Expected in-scope directory count equals actual `SPECS.md` count.
- Every expected directory contains exactly one direct `SPECS.md`.
- There are no missing or unexpected specification locations.
- The root index contains exactly one valid link for every in-scope subfolder.
- Existing `SPECS.md` files do not keep obsolete directories in scope.

### Structure

- Every specification contains sections 1 through 14.
- Every non-root specification contains section 15 for unknowns and review
  items.
- The root contains section 15 for the repository index and section 16 for
  unknowns and review items.
- Every specification includes metadata, draft/review status, and an authority
  notice.
- Every specification contains exactly one Mermaid diagram.
- Markdown and diagram fences are balanced.
- Tables have headers and consistent column counts.
- No conflict markers, unfinished template tokens, or accidental placeholders
  remain.

### Links and evidence

- Resolve every relative Markdown link from the directory containing its
  specification.
- Broken relative-link count is zero.
- Parent links resolve.
- Child links resolve.
- Root-index links resolve.
- Evidence links refer to existing repository files.
- No excluded `openwiki/` page is cited as evidence.

### Exclusion and safety boundaries

- No `SPECS.md` exists under `.git/`, `openwiki/`, ignored dependency trees,
  caches, virtual environments, or transient build output because of this task.
- No temporary generator or validation script remains.
- No specification links to a removed temporary script.
- No secret, credential, personal data, production payload, or large source
  block was copied.
- Repository status confirms that this task changed only `SPECS.md` files.
- Pre-existing unrelated modifications remain untouched.

### Content-quality sampling

Inspect at least:

- the root specification and full index;
- a production runtime aggregation folder;
- a production runtime leaf folder;
- a test folder;
- a native or accelerator folder;
- a Rust or other secondary-language folder when present;
- a build or workflow folder;
- a documentation folder;
- a prompt, skill, policy, configuration, artifact, or diagram folder when
  present.

For each sample, verify that intent, inputs, outputs, contracts, interactions,
failures, environment/configuration, resource mapping, diagram, acceptance
scenarios, and evidence are meaningfully specific to that folder.

### Metrics

Report:

- expected directory count;
- generated or refreshed specification count;
- missing and unexpected counts;
- root-index row count;
- relative links checked and broken-link count;
- required-section failures;
- unbalanced-fence failures;
- Mermaid-count failures;
- total line, word, and byte counts;
- explicit excluded boundaries.

## Final response

Respond with the outcome first, then provide:

- a link to the root `SPECS.md`;
- total specification count, distinguishing root and subfolder files;
- exact coverage-validation result;
- relative-link and structure-validation results;
- approximate aggregate size;
- concise coverage summary across major repository areas;
- explicit exclusions and why they were excluded;
- confirmation that only `SPECS.md` files were changed by this task;
- confirmation that application source and tests were not modified;
- confirmation that OpenWiki was neither used nor modified;
- important evidence gaps or maintainer-review requirements.

Do not paste all specifications into chat. The root `SPECS.md` is the handoff
entry point.

---

