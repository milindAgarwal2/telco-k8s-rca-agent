---
name: write-content-tests
description: "Use when asked to create, improve, or review functional tests for Ansible content, especially Molecule scenarios. Maps intended operational outcomes and failure paths to idempotent tests using safe fixtures and Podman-compatible local execution where available."
---

# Write Ansible content tests

Adapted from `ansible-community/ai-forge`. Test the operational outcome of the
content, not the implementation of trusted Ansible modules.

## Procedure

1. Read applicable repository and collection instructions plus the content's
   intended behavior, supported platforms, side effects, and rollback.
2. Determine whether an existing Molecule scenario fits. Extend it before
   creating a parallel scenario.
3. Map requirements and important failure modes to prepare, converge, verify,
   idempotence, and destroy responsibilities.
4. Use the smallest representative fixture. This workspace has Podman available;
   do not assume Docker is installed.
5. Keep create and destroy bounded to resources owned by the scenario. Validate
   resolved names and paths before cleanup.
6. Verify observable state such as files, permissions, services, packages,
   endpoints, or repeated-run change counts. Avoid retesting the internal wiring
   of built-in modules.
7. Test negative inputs and recovery when they are part of the contract.
8. Do not place credentials or live inventory data in a scenario.

## Tooling boundary

Follow root workspace rules for dependency management; do not recommend bare
`pip` or `pip install`. Use the repository's pinned `uv`, Ansible, Molecule, and
container-driver commands. Do not download dependencies or start containers
without authorization.

## Output contract

Return the requirement-to-scenario mapping, files changed, fixture and platform
assumptions, commands, converge and idempotence results, failed/skipped/not-run
checks, cleanup evidence, and remaining target-specific validation.
