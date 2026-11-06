# AIDE Specification MCP

`aide-spec-mcp` is a local, read-only Model Context Protocol (MCP) server for
preparing and reviewing Kiro specifications. It does not generate files or
modify repository content. Instead, it gives Kiro a bounded evidence packet
for `requirements.md`, `design.md`, and `tasks.md`.

## Evidence model

The server keeps desired and current behavior separate:

1. The current user request or selected `jira/*.md` story defines the desired
   outcome.
2. Repository source, schemas, configuration, and tests establish current
   behavior and must be inspected by Kiro before normative implementation
   claims are made.
3. Reviewed specifications outrank generated drafts.
4. `knowledge-base/` supplies primary architecture and design context.
5. Ancestor `SPECS.md` files identify relevant folder contracts.
6. `openwiki/` supplies secondary discovery context.
7. Inference never silently becomes evidence.

All returned documentation is labelled as draft unless separately reviewed by
responsible maintainers or subject-matter experts.

## Tools

- `aide_spec_status` reports source health, boundaries, and limits.
- `aide_list_spec_stories` lists local Jira-style inputs without their bodies.
- `aide_search_spec_evidence` searches evidence for requirements, design,
  tasks, or the complete specification set.
- `aide_resolve_folder_specifications` finds existing ancestor `SPECS.md`
  contracts for affected repository paths.
- `aide_build_spec_context` returns story, architecture, folder-contract,
  Easy Approach to Requirements Syntax (EARS), and review context.
- `aide_build_spec_traceability` returns evidence anchors and required
  story-to-requirement-to-design-to-task-to-test mappings.
- `aide_assess_spec_document` runs objective structural checks on a draft.
- `aide_read_spec_evidence` reads an exact, bounded, redacted range from an
  approved document.
- `aide_refresh_spec_index` rebuilds only the in-memory documentation index.

## Safety boundaries

- No tool writes repository files.
- No tool invokes an external model or network provider.
- Local reads are limited to `knowledge-base/`, `openwiki/`, the configured
  Jira-style story directory, folder `SPECS.md` files, and existing Kiro
  `requirements.md`, `design.md`, or `tasks.md` documents.
- Symlinks and traversal outside the repository are rejected.
- Returned content is size bounded and common credential forms are redacted.
- Mechanical assessment does not claim semantic correctness or approval.

## Run locally

From this directory:

```powershell
uv sync --all-groups --frozen
uv run --offline --frozen aide-spec-mcp
```

The server communicates over standard input/output and is intended to be
started by Kiro from the repository's MCP configuration.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AIDE_SPEC_ROOT` | Inferred repository root | Repository security boundary |
| `AIDE_SPEC_PRIMARY_DIR` | `knowledge-base` | Primary documentation source |
| `AIDE_SPEC_SECONDARY_DIR` | `openwiki` | Secondary documentation source |
| `AIDE_SPEC_STORY_DIR` | `jira` | Jira-style requirement inputs |
| `AIDE_SPEC_MAX_CONTEXT_CHARS` | `50000` | Maximum rendered context size |
| `AIDE_SPEC_MAX_STORY_BYTES` | `2000000` | Maximum local input file size |
| `AIDE_SPEC_MAX_READ_LINES` | `1000` | Maximum local lines per exact read |
| `AIDE_SPEC_MAX_DOCUMENT_CHARS` | `200000` | Draft assessment input ceiling |

## Intended Kiro sequence

1. Call `aide_spec_status` and select the requirement input.
2. Call `aide_build_spec_context` for `requirements`.
3. Inspect and verify the cited current source and focused tests.
4. Draft `requirements.md`, then run `aide_assess_spec_document`.
5. Repeat context and assessment for `design.md` and `tasks.md`.
6. Use `aide_build_spec_traceability` to reconcile the three documents.
7. Present decisions and unknowns for human review before implementation.
