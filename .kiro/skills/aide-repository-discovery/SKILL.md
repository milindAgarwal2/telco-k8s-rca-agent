---
name: aide-repository-discovery
description: "Use when asked to discover, map, inventory, explain, or orient within this repository before planning work. Produces a source-linked inventory and validation guide across application code, Bash, Ansible, Postman, Kubernetes, and GitOps while separating verified facts from gaps."
---

# AIDE repository discovery

Build a bounded map of the repository from primary evidence. Do not implement a
change during discovery unless the user separately requests implementation.

## Procedure

1. Read the nearest applicable `AGENTS.md` and repository instructions before
   inspecting the requested scope.
2. Confirm the repository revision and the requested scope. Do not silently
   expand a folder-level request to the whole repository.
3. Classify relevant material as application code, tests, Bash operations,
   Ansible content, Postman collections, Kubernetes resources, GitOps content,
   documentation, generated artifacts, or unknown.
4. Locate entry points, dependencies, configuration, interfaces, data stores,
   operational scripts, tests, fixtures, and existing validation commands.
5. Consult `knowledge-base/` for reviewed design context and `openwiki/` for
   secondary discovery when useful. Verify important claims against source and
   tests. A generated page is not source authority.
6. Record missing, contradictory, stale, or inaccessible evidence as a gap. Do
   not fill gaps with plausible behaviour.
7. Separate static checks from commands that execute code or contact a target.
   Run only checks authorized by the active request.

## Output contract

Return a scoped inventory containing:

- the scope and repository revision;
- source-linked components and their purpose;
- inputs, outputs, dependencies, configuration, and interaction points;
- entry points and execution paths supported by evidence;
- local validations versus hardware, service, cluster, or credential-dependent
  validations;
- explicit gaps, contradictions, and follow-up questions.

Label every material statement as verified, inferred, or unresolved. Include
the exact source path for verified claims and name the evidence behind any
inference.

## Boundaries

Do not expose secrets, run destructive commands, contact external services, or
modify repository files merely to improve the inventory. Discovery does not
grant access to an MCP server, cluster, database, or model endpoint.
