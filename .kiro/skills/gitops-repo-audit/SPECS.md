# GitOps repository audit skill specification

## Intent

Assess a Flux repository's structure, correctness, compatibility, security, and
operational readiness from source evidence.

## Contract

The audit is revision-scoped, relationship-aware, source-linked, and separates
repository findings from questions requiring live cluster evidence.

## Failure handling

Missing renderers, schemas, API information, or encrypted inputs are reported as
not-run checks with their impact on confidence.
