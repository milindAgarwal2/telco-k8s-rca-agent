# Implementation Plan

| Field | Value |
|-------|-------|
| Spec | `incident-persistence-postgres` |
| Phase | Tasks (requirements + design approved) |
| Baseline commit | `2f4774f` |
| Status | Draft - awaiting review before execution |

Notes: tasks are incremental and test-driven. Each builds on the previous one.
Decisions D1-D6 are fixed (mandatory DB; psycopg v3 sync core dep; retain while
DB lasts; one table/store + JSONB; sync write-through off-loop; docker PG
automated). Keep the agent read-only toward Kubernetes throughout. Checkpoints
to run: `make check` (ruff + pytest); DB-backed tests gated by a skip-if-no-DB
marker so the suite still runs without PostgreSQL.

## Overview

This plan implements durable incident and runbook-query-log persistence backed by
a mandatory PostgreSQL `db-pg` pod. Work proceeds bottom-up: config and the
store layer first (with round-trip tests), then wiring into the existing
`EventWatcher` and `QueryLog` write points and the app startup rehydration,
then the restart-survival and failure-mode tests, then the Helm and docker
deployment of PostgreSQL, and finally a security review and full verification.

## Task Dependency Graph

- Task 1 (config + dependency) has no prerequisites.
- Task 2 (store skeleton + schema) depends on Task 1.
- Tasks 3 and 4 (IncidentStore, QueryLogStore) depend on Task 2 and can proceed in parallel.
- Task 5 (singleton + lifespan rehydrate + readiness) depends on Tasks 3 and 4.
- Task 6 (incident write-through) depends on Tasks 3 and 5.
- Task 7 (query-log write-through) depends on Tasks 4 and 5.
- Task 8 (restart/read integration tests) depends on Tasks 6 and 7.
- Task 9 (failure-mode tests) depends on Task 5.
- Task 10 (retention) depends on Tasks 6 and 7.
- Task 11 (Helm PG) and Task 12 (docker PG) depend on Task 1 and can proceed in parallel with each other and with the app-code tasks once the config contract is fixed.
- Task 13 (security review) depends on Tasks 11 and 12.
- Task 14 (spec reconcile + full verification) depends on all prior tasks.

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"] },
    { "wave": 2, "tasks": ["2"] },
    { "wave": 3, "tasks": ["3", "4", "11", "12"] },
    { "wave": 4, "tasks": ["5"] },
    { "wave": 5, "tasks": ["6", "7", "9"] },
    { "wave": 6, "tasks": ["8", "10", "13"] },
    { "wave": 7, "tasks": ["14"] }
  ],
  "dependencies": {
    "1": [],
    "2": ["1"],
    "3": ["2"],
    "4": ["2"],
    "5": ["3", "4"],
    "6": ["3", "5"],
    "7": ["4", "5"],
    "8": ["6", "7"],
    "9": ["5"],
    "10": ["6", "7"],
    "11": ["1"],
    "12": ["1"],
    "13": ["11", "12"],
    "14": ["8", "9", "10", "13"]
  }
}
```

## Tasks

- [x] 1. Add configuration and the core dependency
  - Add `database_url: str | None` to `Settings` in `src/rca_agent/config.py` (env `RCA_DATABASE_URL`).
  - Add `psycopg[binary]>=3.1` and `psycopg_pool>=3.2` to `requirements.txt` and the `pyproject.toml` core dependencies (not an extra, per D2).
  - Add a unit test asserting the setting reads from `RCA_DATABASE_URL`.
  - _Requirements: 4.2_

- [x] 2. Create the store package skeleton and schema
  - [x] 2.1 Create `src/rca_agent/store/` with `db.py` defining `Database` (psycopg_pool `ConnectionPool`), `connect_with_retry` (bounded backoff), `is_ready()`, and `ensure_schema()`.
    - `ensure_schema()` issues idempotent `CREATE TABLE IF NOT EXISTS` for `incidents` and `runbook_query_log` plus the indexes from the design.
    - Raise a clear `ConfigurationError` when `RCA_DATABASE_URL` is unset (fail fast).
    - _Requirements: 4.1, 4.3, 4.4_
  - [x] 2.2 Add a test that `ensure_schema()` is idempotent (run twice, no error) against a disposable PostgreSQL (skip-if-no-DB marker).
    - _Requirements: 4.4_

- [x] 3. Implement the IncidentStore with round-trip tests
  - [x] 3.1 Implement `store/incident_store.py`: `upsert(report)` (INSERT ... ON CONFLICT (incident_id) DO UPDATE), `load_recent(limit)`, `get(incident_id)`, `count()`. Serialize with `IncidentReport.model_dump(mode="json")` into the `payload` JSONB and mirror the typed columns.
    - _Requirements: 2.1, 2.5_
  - [x] 3.2 Write round-trip tests: `model -> upsert -> load/get -> model` equals the original for all fields incl. nested `hypotheses`, `evidence`, `citations`, `service_area`, `related_incidents`; and upsert of the same `incident_id` updates in place (no duplicate row).
    - _Requirements: 2.5, 7.3_

- [x] 4. Implement the QueryLogStore with round-trip tests
  - [x] 4.1 Implement `store/query_log_store.py`: `append(entry)`, `load_recent(limit)` (newest first), `clear()` (TRUNCATE), `stats()` (total/positive/negative via SQL counts). Store the full `QueryLogEntry` incl. `hit_titles` in `payload`.
    - _Requirements: 9.1, 9.2_
  - [x] 4.2 Write tests: entry round-trip (incl. `hit_titles`), `stats()` matches in-memory stats, and `clear()` empties the table.
    - _Requirements: 9.2, 9.4, 9.5_

- [x] 5. Wire the store singleton and startup lifecycle
  - [x] 5.1 Add `get_store()` lru_cache singleton (mirroring `get_settings`/`get_query_log`) constructing `Database` + the two stores from `Settings`.
    - _Requirements: 4.1_
  - [x] 5.2 In `webhook/app.py` `_lifespan`, before `yield`: construct the store, `connect_with_retry`, `ensure_schema()`, then rehydrate `EventWatcher.incidents` and the `QueryLog` from `load_recent(...)`. Wrap blocking calls in `asyncio.to_thread`.
    - _Requirements: 3.1, 9.3_
  - [x] 5.3 Make `/readyz` report not-ready until the DB connects; keep `/healthz` independent of the DB.
    - _Requirements: 5.1, 5.2_

- [x] 6. Persist incidents at the EventWatcher write points (write-through)
  - [x] 6.1 Inject the incident store into `EventWatcher`; call `upsert` from `_store`, and after each mutation in `reconcile_status`, `_merge_into_open_anchor`, and `_correlate`. Run the synchronous write via a thread when on the event loop (D5).
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 5.3_
  - [x] 6.2 Make each write non-fatal: on failure, log and keep the in-memory copy; do not raise into the poll loop or the request. Re-persist on the next mutation.
    - _Requirements: 5.3, 5.4_
  - [x] 6.3 Persist webhook-posted incidents via `record_external_incident` (same store call).
    - _Requirements: 2.2_

- [x] 7. Persist the runbook query log at its write point
  - [x] 7.1 Inject the query-log store into `QueryLog`; call `append(entry)` inside `record(...)`, non-fatal on failure.
    - _Requirements: 9.1, 9.6_
  - [x] 7.2 Make `QueryLog.clear()` (and `DELETE /runbook-queries`) clear both memory and DB rows so a cleared log stays cleared across restarts.
    - _Requirements: 9.5_

- [x] 8. Restart-survival and read-path integration tests
  - [x] 8.1 Integration test (FastAPI `TestClient`): create incidents, flip one to inactive, then simulate a restart by constructing a fresh `EventWatcher` and rehydrating from the DB. Assert `/incidents?status=inactive` returns the previously-inactive incident (the exact production failure).
    - _Requirements: 3.2, 3.3_
  - [x] 8.2 Integration test: runbook query log survives the same simulated restart via `/runbook-queries`; and a durable `DELETE /runbook-queries` stays empty after rehydration.
    - _Requirements: 9.3, 9.5_
  - [x] 8.3 Confirm `/incidents`, `/incidents/{id}`, and tab responses keep identical shapes whether freshly created or reloaded; add optional DB fallback for ids beyond the in-memory cache.
    - _Requirements: 7.1, 7.2, 8.3_

- [x] 9. Failure-mode tests (non-fatal DB)
  - Point the agent at an unreachable DB: assert `/healthz` stays OK, `/readyz` is not-ready, the process does not crash, and a runtime write failure is logged without breaking the poll loop.
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 10. Retention behavior
  - Verify no application-level pruning occurs (history grows with the DB) and that the in-memory caches remain capped while the DB retains the full set; a read can page beyond the in-memory cap.
  - _Requirements: 8.1, 8.2, 8.3_

- [x] 11. Helm: add the db-pg PostgreSQL pod (Req 1)
  - [x] 11.1 Add `deploy/helm/templates/postgres-statefulset.yaml` (single replica, `volumeClaimTemplates` PVC for the PG data dir) and `postgres-service.yaml` (ClusterIP `db-pg`, in-namespace only).
    - _Requirements: 1.1, 1.2, 6.3_
  - [x] 11.2 Add `postgres-secret.yaml` (or reference an existing Secret) for PG credentials; inject `RCA_DATABASE_URL` into the agent Deployment from that Secret. Add a `postgres:` block and `agent.databaseUrlSecret` to `values.yaml`.
    - _Requirements: 6.1_
  - [x] 11.3 Validate with `helm lint` and `helm template`; confirm the agent ClusterRole still grants only get/list/watch (DB is not a cluster write).
    - _Requirements: 1.5_

- [x] 12. Docker/Cobra: automate the PostgreSQL container (Req 1.4, D6)
  - Extend `docker/deploy-cobra.sh` to start a pinned PostgreSQL container with a host-mounted data volume and a password from an env/file (not hardcoded), wait for PG readiness (pg_isready / TCP probe), then start the agent with `RCA_DATABASE_URL` pointing at 127.0.0.1:5432. Mirror the existing LLM-sidecar wait pattern.
  - Verify the db-pg contents survive a container restart (stop/start the agent; history persists).
  - _Requirements: 1.3, 1.4, 6.1_

- [x] 13. Security review of credentials and stored data
  - Confirm PG credentials come only from a Secret/env (never committed), the DB is not externally exposed, stored payloads are documented as sensitive, and the read-only-toward-Kubernetes posture is unchanged.
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 14. Reconcile specs and run full verification
  - Update affected `SPECS.md` (root/src `RCA_DATABASE_URL`, detection, rag, webhook, deploy/helm, docker) and add `src/rca_agent/store/SPECS.md`.
  - Run `make check` (ruff + pytest). Ensure the suite passes with and without a test PostgreSQL (skip-if-no-DB marker).
  - _Requirements: 2.5, 3.3, 4.4, 5.1, 7.3, 9.2_

## Notes

- Keep changes additive: the in-memory caches and the 200-item cap stay; the DB is the durable superset.
- All DB-backed tests use a skip-if-no-DB marker so `make check` still runs without PostgreSQL.
- Preserve the read-only-toward-Kubernetes posture: the database is the agent's own datastore, never a cluster write.
- Synchronous store calls on the event loop must be wrapped in `asyncio.to_thread` (D5) to avoid blocking.
