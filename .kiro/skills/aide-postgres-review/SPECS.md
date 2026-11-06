# PostgreSQL review skill specification

## Intent

Assess PostgreSQL changes for correctness, compatibility, locking, query-plan,
rollout, and recovery risk.

## Contract

Review is version- and volume-aware, distinguishes static plans from executed
evidence, addresses mixed-version application behavior, and names irreversible
operations.

## Failure handling

Missing target data, statistics, versions, or authorization is reported as an
evidence gap. The skill never substitutes a production connection or exposes
record data.
