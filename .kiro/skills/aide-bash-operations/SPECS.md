# Bash operations skill specification

## Intent

Make shell operations reviewable as explicit interfaces with controlled side
effects and deterministic failure behavior.

## Contract

Inputs, outputs, exit codes, dependencies, quoting, retries, cleanup,
idempotency, and targets are documented. Static analysis and target execution
are separate activities.

## Failure handling

Execution failures preserve the primary error and perform only bounded cleanup.
Destructive paths are exercised only in resolved, isolated fixtures.
