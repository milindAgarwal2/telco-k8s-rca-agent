---
name: skill-creator
description: "Use when asked to create, scaffold, evaluate, refine, or troubleshoot a Kiro skill in this workspace. Produces a concise SKILL.md with discriminating activation metadata, progressive instructions, reusable resources only when justified, and validation and activation tests."
---

# Create Kiro skills

Adapted from the skill-authoring workflow in `anthropics/skills` and the Kiro
skill format. A skill is a focused operational playbook, not a general document
dump.

## Procedure

1. Collect two or more representative user requests that should activate the
   skill and at least two near-miss requests that should not.
2. Define the skill's outcome, authority boundary, required evidence, failure
   behavior, and expected output before writing instructions.
3. Search existing `.kiro/skills/` and the staged `skills/` catalog. Extend a
   suitable skill instead of creating an overlapping one.
4. Choose a lowercase hyphenated name no longer than 64 characters.
5. Create `<name>/SKILL.md` with YAML frontmatter containing only the required
   `name` and a precise `description`. The description must say when to use the
   skill and distinguish nearby tasks.
6. Write imperative, task-focused instructions. Put the critical workflow,
   safety boundary, and output contract in `SKILL.md`.
7. Add scripts only for deterministic or repeatedly error-prone operations.
   Add references only for detail that is needed conditionally. Do not duplicate
   the same guidance across files.
8. Test direct invocation, expected automatic activation, and near-miss
   non-activation in a new Kiro session.
9. Evaluate the resulting output against a fixed task and improve the smallest
   instruction that addresses a repeated failure.

## Validation checklist

- valid frontmatter and directory/name match;
- name and description within Kiro limits;
- clear activation and non-activation boundary;
- no embedded credentials or environment-specific secret values;
- no permission implied beyond the active request;
- referenced files exist and scripts have safe failure behavior;
- outputs and stop conditions are explicit;
- concise enough to avoid crowding task context.

## Output contract

Return created or changed skill paths, activation examples, near misses,
dependencies, validations performed, and remaining evaluation gaps. Do not
install the skill unless installation is part of the request.
