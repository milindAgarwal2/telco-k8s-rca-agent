---
type: guide
title: Change-Impact Navigation with Folder Specs
description: How to use the folder SPECS.md files and the specification relationship map to bound the impact of a contract change before editing, then verify declared relationships against source.
tags:
  - change-impact
  - specifications
  - relationship-map
  - navigation
  - review
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T20:42:17.288Z
sources:
  - id: openwiki-source-2020a45c10b9e6676b1010fb
    resource: repo://knowledge-base/SPECS-RELATIONSHIP-MAP.md
  - id: openwiki-source-f08cd2e6c47f0701e23dbd50
    resource: repo://SPECS.md
  - id: openwiki-source-88f832103715fca67aef3941
    resource: repo://src/rca_agent/models/incident.py
  - id: openwiki-source-6d0adc67a2d0fd579ff1c4fe
    resource: repo://src/rca_agent/models/SPECS.md
  - id: openwiki-source-c98e845415fa00cea24bb794
    resource: repo://src/rca_agent/reasoning/SPECS.md
  - id: openwiki-source-b124b42611a79951cbac3553
    resource: repo://src/rca_agent/webhook/SPECS.md
generated: { by: "kiro", at: "2026-11-03T20:42:17.288Z" }
---

# Change-Impact Navigation with Folder Specs

> Draft pending subject-matter expert (SME) review. This page describes a
> navigation aid built from draft specifications. Treat declared relationships
> as review signals and verify them against source before relying on them.

Before you change a folder's contract, you want to know what else could break.
This repository ships two navigation aids for that: a per-folder specification
file and a repository-wide relationship map. This page explains what each one
proves, what it does **not** prove, and a bounded procedure for using them.

## One SPECS.md per folder

Each project folder contains exactly one `SPECS.md` file. Its section 6,
"Interaction points", declares the folder's **outbound** dependencies (folders
it depends on) and its **inbound** consumers (folders that depend on it). The
repository-root [`SPECS.md`](../SPECS.md) indexes every folder specification in
its "Repository specification index" section, so you can find any folder's
contract from one place.

For example, `src/rca_agent/models/SPECS.md` section 6 lists one outbound edge
(to `impact/` for the `ServiceAreaImpact` import) and six inbound consumers
(`webhook/`, `detection/`, `reasoning/`, `tools/`, `eval/`, and the parent
package). That makes `models/` the highest-consumed contract in the application.

## The relationship map is a summary, not a call graph

`knowledge-base/SPECS-RELATIONSHIP-MAP.md` is a single navigation and
impact-analysis summary built by normalizing every folder's section-6 table
into one catalog of structural parent/child edges and dependency edges. It is
useful for seeing hubs, leaves, and cross-area dependency concentration at a
glance.

It is **not** a runtime call graph. The map states its own limit directly: a
declared dependency edge proves that a specification records a relationship; it
does **not** prove a specific runtime call, execution order, data format, or
deployment topology. Absence from the map means "not declared by the parsed
specification set", not "cannot happen at runtime". The map and its node/edge
counts are draft specification evidence, not verified runtime facts.

For how the system actually behaves at run time, use the source-grounded pages:
[Architecture and Components](architecture.md), the
[Reasoning Pipeline](reasoning-pipeline.md), and the
[Request Lifecycle](request-lifecycle.md).

## A bounded impact-analysis procedure

When you are about to change a folder's contract:

1. **Locate the folder.** Find its row in the relationship map's node catalog
   (or open its `SPECS.md` directly). Read its structural parent, child count,
   and declared outbound/inbound degrees.
2. **Read its section 6.** The folder's own "Interaction points" table is the
   authoritative list of what it depends on (outbound contracts it must honor)
   and what depends on it (inbound consumers a breaking change will affect).
3. **List the affected consumers.** Every inbound edge is a consumer to check.
4. **Verify against source.** Open the cited source before concluding. A
   declared edge is a starting point, not proof of a runtime path.
5. **Update together.** Change the code, the affected folder specs, and the
   smallest verification that proves the new behavior in one change.

### Worked example: changing the incident report

Suppose you add a field to `IncidentReport`
(`src/rca_agent/models/incident.py`). Step 2 shows `models/` is consumed by
`reasoning/`, `webhook/`, `detection/`, `tools/`, `eval/`, and the parent
package. Step 3 makes those the consumers to check.

Step 4 — verifying against source — confirms a key compatibility rule: the
schema keeps newer fields **defaulted**. `affected_anchor`, `anchor_kind`,
`affected_pods`, `resolved_at`, and similar fields all carry defaults in
`src/rca_agent/models/incident.py`, so older serialized reports and existing
callers still parse. That is a *direct-evidence* constraint on how you should
add a field: keep it optional and defaulted, or you break the inbound
consumers the relationship map just listed for you.

## Read declared edges as review signals, not verdicts

Two cautions the relationship map itself raises:

- **A one-sided edge is not an automatic defect.** The map records whether each
  edge was declared from the outbound side, the inbound side, or both. An
  outbound-only or inbound-only edge (for example, documentation or fixture
  references) is a review signal to confirm, not a broken contract.
- **A folder relationship is not a proven runtime call.** Dynamic and
  deployment-only relationships (the live Kubernetes read path, the LLM sidecar
  call, the background event-watch loop) appear as declared edges but are not
  proven as runtime calls by a static map. Confirm them against source and
  runtime behavior when the detail matters.

See [Unresolved Questions and Known Gaps](unresolved-questions.md) for the
specific review items the specifications flag.

## Related pages

- [Architecture and Components](architecture.md)
- [Concept: Service Anchoring and the Incident Model](concepts-service-anchoring.md)
- [Reasoning: Extractive Pipeline and LLM Rerank](reasoning-pipeline.md)
- [System Overview](overview.md)
- [Unresolved Questions and Known Gaps](unresolved-questions.md)
