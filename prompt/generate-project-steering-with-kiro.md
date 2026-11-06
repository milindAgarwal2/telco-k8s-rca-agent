# Kiro Prompt: Generate Project-Specific Steering

Run this prompt from the target repository root after the AIDE baseline and
OpenWiki initialization have completed. The guided installer appends the exact
list of missing steering files to the prompt.

---

Create only the missing project-specific Kiro steering files identified at the
end of this prompt:

- `.kiro/steering/product.md`
- `.kiro/steering/structure.md`
- `.kiro/steering/tech.md`

Never overwrite, rewrite, rename, or delete an existing steering file. If none
of these files is missing, make no changes.

## Evidence authority

Use this precedence:

`source, schemas, and build definitions → focused tests → reviewed knowledge-base documents → OpenWiki draft pages → other generated summaries`

Read applicable `AGENTS.md` files first. Inspect the smallest useful set of
repository files needed to establish the project purpose, architecture,
technology, and working conventions. Use `knowledge-base/` as the primary
curated documentation source when it contains reviewed material. Use
`openwiki/index.md`, `openwiki/quickstart.md`, and relevant linked OpenWiki
pages as secondary navigation and explanatory context. Verify material claims
against current source, schemas, build definitions, configuration, or focused
tests.

Distinguish direct evidence from inference and mark unresolved questions.
Never invent a component, dependency, command, deployment, interface, data
store, runtime behavior, business rule, customer variant, or support policy.

## Common file contract

Each created file must begin with:

```yaml
---
inclusion: always
---
```

Keep the content concise enough to be useful as always-included Kiro context,
but specific enough to prevent generic or incorrect implementation choices.
Prefer exact repository-relative paths. Do not paste large source blocks,
credentials, personal data, production records, or proprietary payloads.

### product.md

Describe:

- the application's purpose and users;
- primary capabilities and observable outcomes;
- in-scope and out-of-scope responsibilities;
- important domain concepts and terminology;
- externally visible interfaces and operational modes;
- business or compatibility constraints proven by evidence;
- known variants, feature controls, or unresolved product questions; and
- the requirement that generated documentation remains draft until reviewed.

Do not turn the file into a feature wish list or modernization proposal.

### structure.md

Describe:

- the repository's major directories and what owns each responsibility;
- runtime, build, test, deployment, documentation, and tooling entrypoints;
- important module boundaries and dependency direction;
- where contracts, schemas, configurations, generated artifacts, and tests
  live;
- how to navigate from a requested change to likely producers, consumers, and
  verification;
- directories that must not be manually edited; and
- naming or placement conventions established by current evidence.

Avoid exhaustive file inventories. Explain structure in terms of engineering
decisions and navigation.

### tech.md

Describe:

- languages, runtimes, package/build systems, frameworks, and data technologies;
- supported development and validation commands already documented by the
  repository;
- configuration sources and environment-variable names without secret values;
- runtime topology, concurrency, persistence, protocols, and external systems
  where proven;
- platform, hardware, version, and deployment constraints;
- testing layers and when special infrastructure is required;
- security and operational boundaries; and
- uncertain or environment-specific assumptions requiring maintainer review.

Do not install dependencies, run servers, contact live services, or infer
production configuration from examples.

## Validation

Before finishing:

1. Confirm only the requested missing steering files were created.
2. Confirm each created file has valid always-included frontmatter.
3. Check headings, Markdown links, diagrams, and code fences.
4. Search for placeholders, unsupported claims, secrets, and accidental large
   source excerpts.
5. Confirm no application source, tests, existing steering, OpenWiki content,
   knowledge-base content, or unrelated files were modified.
6. Report created paths, key evidence used, inferences, and unresolved items.

## Installer-selected files

The guided installer will append the authoritative missing-file list below.
Create only those paths.

