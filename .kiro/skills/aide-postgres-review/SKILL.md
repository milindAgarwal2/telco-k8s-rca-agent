---
name: aide-postgres-review
description: "Use when asked to review a PostgreSQL schema, migration, index, query, transaction, or database compatibility change. Assesses locking, plans, rollout, recovery, and verification; do not activate merely because an application happens to store data in PostgreSQL."
---

# AIDE PostgreSQL review

Review the proposed database behavior without connecting to a database unless
the user explicitly authorizes a named non-production target.

## Procedure

1. Identify supported PostgreSQL versions, schema ownership, migration tool,
   deployment order, data volume assumptions, availability target, and rollback
   constraints from repository evidence.
2. Review DDL and migrations for transactional behavior, lock level and
   duration, table rewrites, validation scans, default evaluation, concurrent
   index restrictions, dependency order, and repeat or partial-run behavior.
3. Review application compatibility during mixed-version rollout, including
   reads, writes, constraints, nullability, enum or type changes, and feature
   gating.
4. Review queries for semantics, cardinality assumptions, selectivity, join
   order, indexes, statistics, parameter behavior, pagination, transactions,
   isolation, deadlocks, and timeouts.
5. Use an existing sanitized fixture or approved lab snapshot for execution.
   `EXPLAIN` is static planning evidence; `EXPLAIN ANALYZE` executes the query
   and requires authorization appropriate to its target and side effects.
6. Define expand-and-contract or another safe rollout when one-step deployment
   can break compatibility.
7. Define recovery for partial migration, failed deployment, and data repair.
   Do not describe irreversible rollback as safe.

## Output contract

Lead with prioritized findings and exact SQL or source locations. Include
version and volume assumptions, lock and compatibility analysis, plan evidence,
rollout order, verification, recovery, checks not run, and residual risk.

Never print credentials, production rows, or sensitive query parameters. A
successful migration in an empty database is not proof of production-safe lock
duration.
