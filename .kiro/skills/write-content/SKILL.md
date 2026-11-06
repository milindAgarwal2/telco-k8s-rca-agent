---
name: write-content
description: "Use when asked to author, improve, or review Ansible playbooks, tasks, handlers, roles, templates, variables, or inventories. Produces clear, idempotent content with fully qualified names, explicit state, bounded targets, and documented approval and rollback behavior."
---

# Write Ansible content

Adapted from `ansible-community/ai-forge` for this Kiro workspace. Read
`skills/UPSTREAM.md` in the source catalog when provenance is needed.

## Procedure

1. Read applicable repository instructions and existing Ansible conventions.
2. Identify whether the content is standalone or part of a collection or role.
   Reuse nearby variables, handlers, module defaults, and layout.
3. Define the lab or production inventory boundary, affected hosts, privilege
   needs, secrets source, check-mode limits, approval point, and rollback.
4. Prefer `ansible.builtin` modules, then vendor or verified collections, then
   reviewed project modules. Use fully qualified collection names.
5. Use an explicit desired state, meaningful task names, typed variables where
   practical, and role-prefixed variable names.
6. Prefer purpose-built modules over `shell` or `raw`. Use `command` only when
   shell features are not needed. When a shell is unavoidable, document the
   reason, validate inputs, quote safely, and define `changed_when` and
   `failed_when` deliberately.
7. Use handlers for restart or reload behavior and notify them only on change.
8. Express expected nonzero outcomes with `failed_when`; do not hide failures
   with blanket `ignore_errors`.
9. Keep templates deterministic and avoid exposing secret values in output.

## Validation

Use the repository's existing Ansible validation commands. At minimum, plan for
YAML parsing, `ansible-lint`, syntax check with an explicit safe inventory, and
check mode where supported. Runtime execution requires a named target and user
approval; check mode does not prove that a service recovered.

## Output contract

For authoring, return the changed content plus inventory boundary, variables,
side effects, idempotency mechanism, handlers, failure behavior, approval gate,
rollback, and checks. For review-only requests, return source-linked findings
without modifying files.

