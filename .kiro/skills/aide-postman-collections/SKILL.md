---
name: aide-postman-collections
description: "Use when asked to inventory, explain, review, deduplicate, subset, or improve a large Postman collection. Starts with deterministic offline parsing of requests, variables, inherited authentication, scripts, and assertions before loading only the relevant subset for semantic analysis."
---

# AIDE Postman collections

Default to offline analysis. A collection file can contain credentials,
production URLs, sample records, and executable scripts; treat it as sensitive
input.

## Deterministic inventory first

From the repository root, use the bundled standard-library parser:

```powershell
uv run python skills/aide-postman-collections/scripts/inventory_collection.py `
    path\to\collection.json
```

When installed under Kiro, replace `skills/` with `.kiro/skills/`. The parser
reports structure, URL templates, variable names, auth types, script and test
counts, and duplicate candidates. It does not print variable values, headers,
request bodies, authentication material, or script contents.

## Procedure

1. Record file hash, Postman schema, collection size, and parse warnings.
2. Inventory folders and requests deterministically before asking for semantic
   interpretation.
3. Trace variable names through collection, folder, request, environment, and
   local scopes without disclosing their values.
4. Identify inherited authentication by type and scope. Never reproduce tokens
   or cookie values.
5. Count pre-request and test scripts, then inspect only reviewed scripts needed
   for the question.
6. Flag duplicate candidates by normalized method and URL as candidates, not
   proven duplicates; compare behavior, auth, body, and tests before deciding.
7. Extract only a reviewed, dependency-complete subset when a focused artifact
   is requested. Preserve original identifiers, order, variables, and behavior.
8. Improve assertions against observable response contracts. Avoid fragile
   assertions tied to volatile values.

## Boundaries and output

Do not send requests, contact collection hosts, authenticate, or run collection
scripts unless separately requested with an approved target. Return inventory
evidence, variable and auth flow, script/assertion coverage, duplicate
candidates, selected subset rationale, findings, and unresolved dependencies.
