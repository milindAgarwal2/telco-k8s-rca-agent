# .kiro/skills/openwiki Folder Specification

## Specification metadata

| Item | Value |
|---|---|
| Specification ID | `FSPEC-6FB96361EB` |
| Folder | `.kiro/skills/openwiki` |
| Role | Kiro workspace configuration and skills |
| Evidence baseline | Commit `b2dc864bb668da328aee8a8b0b72a0ad13c82252` |
| Generated | 2026-08-31 |
| Status | Draft; normative after maintainer review |
| Parent specification | [.kiro/skills](<../SPECS.md>) |

> Source code, tests, schemas, and build definitions remain authoritative.
> This draft captures current intent and contracts for spec-driven
> development and must be reviewed whenever behavior changes.

## 1. Intent and significance

The `.kiro/skills/openwiki` folder defines Kiro workspace behavior, steering, or skills. This directory focuses on **Openwiki** and coordinates 1 direct files with 1 immediate subfolders.

This is an aggregation boundary. Child specifications refine the
responsibilities stated here and must stay compatible with this contract.

## 2. Scope and contents

| Measure | Value |
|---|---:|
| Direct files | 1 |
| Immediate subfolders | 1 |
| Direct artifact size | 7859 bytes |
| Discovered symbols, capped scan | 0 |

Direct content types:

- Markdown documentation: 1

## 3. Inputs

- No direct internal folder import was identified in the bounded scan.
- Call arguments, typed configuration, request/model state, and resources
  supplied by parent components are the primary runtime inputs.

## 4. Outputs

- Return values, mutated state, serialized messages, registrations, or
  resources consumed by downstream runtime layers.
- Errors and observability signals are outputs when the contract cannot be
  satisfied.

## 5. Contracts and models

### 5.1 Behavioral contracts

1. Validate inputs at the narrowest layer with sufficient context.
2. Treat public names, formats, registry keys, tensor properties, protocol
   fields, and lifecycle ordering as compatibility-sensitive when exposed.
3. Preserve documented interactions and ownership, or update this and every
   affected producer/consumer specification before implementation.
4. Make failure explicit through an exception, result, status, assertion, or
   test outcome; never silently convert invalid state into valid output.
5. Keep optional behavior gated by configuration, platform, model, dependency,
   connector, or test marker.

### 5.2 Declared models and callable surface

No class, function, struct, enum, or trait declaration was found in direct
files by the bounded scan. Contracts are primarily file-format, artifact,
child-module, or parent-integration contracts.

### 5.3 Required invariants

- Direct artifacts remain attributable to this folder's stated intent.
- Parent and child specifications do not contradict ownership or lifecycle.
- New inputs, outputs, environment variables, exceptions, persistent memory,
  or dependencies require a specification update.
- Behavior changes include focused validation at the cheapest level that
  proves the contract.

## 6. Interaction points

| Direction | Folder | Interaction |
|---|---|---|
| Parent | [.kiro/skills](<../SPECS.md>) | Containing contract and integration context. |
| Child | [.kiro/skills/openwiki/agents](<agents/SPECS.md>) | Refines a responsibility owned here. |

This is a bounded static scan. Add dynamic imports, registry lookup, entry
points, generated bindings, callbacks, connectors, and external systems when
a change introduces or depends on them.

## 7. Exception and error handling

No explicit local raise, catch, result, or native guard was identified in
the direct-file scan. Validation may be owned by a parent, dependency,
schema/tooling engine, or child folder.

Required failure contract:

- preserve original diagnostic context;
- clean up resources owned by this folder;
- propagate to the layer that can produce the correct external result;
- never report success after partial mutation unless rollback or idempotent
  retry is explicit.

## 8. Environment variables and configuration

No direct environment-variable access was identified. Configuration may
still arrive through typed objects, arguments, build variables, fixtures,
or parent components. New environment coupling must document its name,
default, parser, validation, security impact, and tests here.

## 9. Storage, memory, and resource map

This covers resources referenced directly here. Transitive allocations remain
governed by their owning specifications.

| Resource | Typical owner | Lifetime | Release or bound |
|---|---|---|---|
| Direct repository artifacts | Version control and maintainers | Repository revision | Review, replacement, or repository cleanup |

Memory-sensitive changes state allocation owner/address space, size and
format, normal and exceptional release, concurrency lifetime, and whether
data is cached, shared, copied, pinned, serialized, or retained.

## 10. Interaction diagram

~~~mermaid
flowchart LR
    IN["Inputs / callers / configuration"] --> HERE[".kiro/skills/openwiki"]
    HERE --> OUT["Outputs / state / artifacts"]
    PARENT["Parent: .kiro/skills"] --> HERE
    HERE --> C0["Child: .kiro/skills/openwiki/agents"]
~~~

The diagram shows direct repository boundaries. Add runtime-only registry,
plugin, callback, connector, and generated-code edges when relevant.

## 11. Cross-cutting design considerations

- **Security and integrity:** preserve provenance, avoid sensitive content,
  validate links/formats, and minimize automation permissions.

## 12. Spec-driven development protocol

For a change in this folder:

1. Update this specification first with intended behavior, contract delta,
   interaction change, failure semantics, and resource impact.
2. Identify affected parent, child, producer, and consumer specifications.
3. Write or update the smallest test or evidence proving the new contract.
4. Implement without silently widening scope.
5. Run the narrowest validation and preserve complete failure output.
6. Reconcile this file with final implementation before review.

### Acceptance scenarios

- **FSPEC-6FB96361EB-AC01 — Intended behavior:** Given valid documented inputs, when
  this responsibility is invoked, then documented outputs are produced
  without violating parent or dependency contracts.
- **FSPEC-6FB96361EB-AC02 — Invalid input or failure:** Given invalid input or a
  dependency failure, then failure is explicit, diagnostic context is
  preserved, and owned resources are released.
- **FSPEC-6FB96361EB-AC03 — Compatibility:** Given an existing supported consumer,
  an internal change preserves the observable contract or versions and
  documents it.
- **FSPEC-6FB96361EB-AC04 — Verification:** Focused validation catches the target
  failure and passes for the implemented behavior.

## 13. Verification strategy

- Run focused unit/component tests for local logic and public contracts.
- Add integration, model, device, or distributed tests only when crossed.
- Confirm repository status contains only intended changes.

## 14. Evidence inventory

| Direct file | Type | Size |
|---|---|---:|
| [SKILL.md](<SKILL.md>) | Markdown documentation | 7859 bytes |

## 15. Unknowns and review items

- Confirm dynamic registry, plugin, callback, and generated-code interactions
  that are invisible to static dependency scanning.
- Confirm deployment-specific environment, model, platform, hardware, and
  distributed assumptions before treating them as guarantees.
- Review whether direct artifacts expose a compatibility surface requiring
  versioning or migration.
- Replace broad generated contracts with precise maintainer-approved rules
  when this folder is the subject of a concrete change.

