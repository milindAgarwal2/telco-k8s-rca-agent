---
name: aide-bash-operations
description: "Use when asked to create, review, explain, test, or troubleshoot Bash scripts or shell command workflows. Documents inputs, outputs, exit codes, side effects, quoting, errors, retries, cleanup, idempotency, and the boundary between static review and target execution."
---

# AIDE Bash operations

Treat shell automation as an operational interface. Review statically before
executing it against any target.

## Analysis contract

For each script or operation identify:

- interpreter and platform assumptions;
- positional arguments, flags, standard input, files, and environment inputs;
- standard output, standard error, files, resources, and exit codes;
- external commands and version assumptions;
- local and remote side effects;
- privilege, credential, network, and target requirements;
- quoting, word splitting, globbing, pipelines, subshells, and signal behavior;
- failure propagation, retries, timeout, cleanup, trap, and partial-state risks;
- repeated-execution, concurrency, locking, and idempotency behavior.

## Authoring rules

1. Follow repository shell conventions and validation scripts.
2. Quote expansions unless deliberate splitting or globbing is documented.
3. Validate required inputs and targets before the first mutation.
4. Use explicit exit behavior; do not assume `set -e` handles every failure.
5. Preserve the original failure while attempting bounded cleanup.
6. Make retries finite, limited to transient operations, and safe to repeat.
7. Use temporary directories and traps for owned temporary state. Never clean a
   broad or unresolved path.
8. Prefer dry-run support for operations with material side effects.

## Verification

Start with parsing and the repository's existing lint commands. Exercise normal,
invalid-input, command-failure, interruption, repeated-run, and cleanup paths
against prepared fixtures. Destructive-path tests must use an isolated fixture
whose resolved path is verified before execution.

Never execute against a live host, cluster, repository, or data set solely
because the script was supplied for review. Name every executed command, target,
exit code, and observed side effect.

## Output contract

Return an interface summary, side-effect map, findings or change, static checks,
fixture execution evidence, checks not run, rollback or cleanup behavior, and
unresolved platform assumptions.
