# Requirements Document

| Field | Value |
|-------|-------|
| Spec | `incident-persistence-postgres` |
| Phase | Requirements (design and tasks not yet written) |
| Baseline commit | `2f4774f` |
| Status | Draft - decisions D1-D6 resolved; Design in progress |

## Introduction

The RCA agent keeps all incident history in a single in-memory Python list
(`EventWatcher.self.incidents`), bounded to 200 items, with no disk
persistence. Any agent process restart therefore erases all active and
inactive incidents. This was confirmed in production on the Cobra jumpserver:
the `rca-agent` container restarted once (clean exit 0, `OOMKilled=false`, not a
crash and not a code redeploy) and `GET /incidents?status=all` subsequently
returned `count:0` / `total_incidents:0` - the full history was lost.

This feature adds durable persistence by introducing a **separate PostgreSQL
pod (`db-pg`)** as the agent's own datastore. Two in-memory stores are made
durable: (a) the full incident history (`IncidentReport` records) and (b) the
runbook query log (each retrieval attempt and its response/hits). Both are
written to PostgreSQL on create/append and rehydrated on startup, so the
dashboard's active/inactive tabs, the `/incidents` API, and the
`/runbook-queries` log all survive restarts, redeploys, and crashes. The
query-log module's own docstring already notes Postgres persistence is the
intended fix for both stores.

The feature must preserve the agent's existing invariants:
- read-only toward Kubernetes (the DB is the agent's own store, not a cluster write);
- single-process agent model and read-only query tooling are unchanged;
  NOTE: per decision D1 the PostgreSQL store is now a REQUIRED dependency of
  the agent (not opt-in). The agent no longer runs with no extra infra; the
  `db-pg` datastore must be present. This is an intentional trade of the
  former zero-infra default for durable history.
- non-fatal on dependency failure (a DB outage must not crash the agent).

### Out of scope (this phase)
- Changing incident detection, reasoning, correlation, or scoring logic.
- Replacing the existing `RCA_INCIDENT_CAPTURE_PATH` JSONL capture (prior art; it
  is a one-way log that does not reload - this feature supersedes its role for
  durable history but does not require removing it).
- Multi-replica / high-availability PostgreSQL. The POC runs a single agent
  replica; HA PG is a later concern.
- Migrating the uploaded runbook document store itself to PostgreSQL (the
  runbook CONTENT store stays as-is; only the query LOG is persisted here).

## Glossary

- **db-pg pod**: a separate Kubernetes pod running PostgreSQL, the agent's durable datastore.
- **Store rehydration**: loading persisted incidents back into the in-memory `EventWatcher.incidents` list at agent startup.
- **Write-through**: persisting an incident to PostgreSQL at the moment it is created or mutated in memory.
- **Mandatory datastore**: per D1 the PostgreSQL `db-pg` store is always the backing store; there is no in-memory-only runtime mode in normal operation.
- **IncidentReport**: the Pydantic v2 output model in `src/rca_agent/models/incident.py` representing one detected fault.
- **EventWatcher**: the component in `src/rca_agent/detection/event_watcher.py` that owns the in-memory incident store.
- **Runbook query log**: the bounded in-memory log in `src/rca_agent/rag/query_log.py` (`QueryLog`, `deque(maxlen=runbook_query_log_max_entries)`) recording each runbook-retrieval attempt.
- **QueryLogEntry**: one query-log record with `timestamp`, `query`, `retriever`, `hit_count`, and `hit_titles` (the response/hits).

## Resolved decisions (D#)

- **D1 (resolved)**: Persistence is **mandatory**, not configurable. The `db-pg`
  PostgreSQL datastore is the only backing store; there is no opt-in flag and no
  in-memory-only runtime mode. Connection details come from the environment
  (`RCA_DATABASE_URL`, value sourced from a Secret), but the feature cannot be
  turned off. Trade-off accepted: the agent now requires the DB to be present.
- **D2 (resolved)**: Driver is **`psycopg` (v3), synchronous**, now a **core**
  dependency (added to `requirements.txt`), because the store is mandatory.
- **D3 (resolved)**: Durable history is retained **as long as the database lasts**
  - no application-level age/count pruning. Bound is the PVC / host volume disk
  capacity. The in-memory list stays capped (200 incidents) for UI/performance,
  but the database keeps the full history; reads can page beyond the in-memory cap.
- **D4 (resolved)**: One table per store. `incidents` and `runbook_query_log`
  each use typed columns for query-worthy fields plus a `JSONB` column holding the
  full serialized record for faithful round-trip (schema detailed in Design).
- **D5 (resolved)**: **Synchronous write-through** on every create/mutation. DB
  writes run off the event loop (in a worker thread, like the existing blocking
  kube calls) so the poll cycle is not blocked.
- **D6 (resolved)**: The `deploy-cobra.sh` docker path **automates** a separate
  `postgres` container with a host-mounted data volume and wires `RCA_DATABASE_URL`
  into the agent container.

## Requirements

### Requirement 1: Separate durable PostgreSQL datastore

**User Story:** As an operator, I want incident data stored in a separate
PostgreSQL pod with persistent storage, so that incident history is not lost
when the agent container restarts.

#### Acceptance Criteria
1. WHEN the Helm chart is installed with persistence enabled, THE SYSTEM SHALL provision a separate `db-pg` pod running PostgreSQL.
2. THE `db-pg` pod SHALL use a PersistentVolumeClaim so that database contents survive pod restarts and rescheduling.
3. WHEN the `db-pg` pod restarts, THE SYSTEM SHALL retain all previously persisted incidents (verified by querying after restart).
4. THE SYSTEM SHALL document an equivalent for the `docker/deploy-cobra.sh` path: a separate `postgres` container with a host-mounted data volume (D6).
5. THE agent's Kubernetes RBAC SHALL remain unchanged (get/list/watch only); the database is the agent's own datastore and SHALL NOT require any Kubernetes write verb.

### Requirement 2: Persist incidents on create and mutation

**User Story:** As an operator, I want every incident and every change to it
written to the database, so that the durable record always matches the live store.

#### Acceptance Criteria
1. WHEN an incident is created via `_store` (event- or status-detected), THE SYSTEM SHALL persist it to PostgreSQL.
2. WHEN an incident is recorded via `record_external_incident` (webhook-posted), THE SYSTEM SHALL persist it to PostgreSQL.
3. WHEN `reconcile_status` flips an incident to `inactive` and sets `resolved_at`, THE SYSTEM SHALL persist the updated `status` and `resolved_at`.
4. WHEN `affected_pods` is extended by anchor merge, or `related_incidents` / correlation note changes, THE SYSTEM SHALL persist the updated incident.
5. THE persisted record SHALL faithfully round-trip every `IncidentReport` field (including nested `hypotheses`, `evidence`, `citations`, `service_area`, `related_incidents`) so a reloaded incident is equivalent to the original.

### Requirement 3: Rehydrate the in-memory store on startup

**User Story:** As an operator, I want the active and inactive tabs to show the
same incidents after a restart as before it, so that I do not lose history.

#### Acceptance Criteria
1. WHEN the agent starts with persistence configured, THE SYSTEM SHALL load persisted incidents from PostgreSQL into `EventWatcher.incidents` before serving `/incidents`.
2. THE reloaded incidents SHALL preserve `status` (active/inactive), `resolved_at`, and `related_incidents` so the tab classification is identical to before the restart.
3. WHEN `/incidents?status=inactive` is queried after a restart, THE SYSTEM SHALL return incidents that were inactive before the restart (the exact scenario that currently fails).
4. IF the number of persisted incidents exceeds the in-memory bound, THE SYSTEM SHALL load at least the most recent up to that bound AND SHALL still be able to serve older incidents per the retention/query policy (D3).

### Requirement 4: Mandatory datastore and startup dependency

**User Story:** As an operator, I want the agent to always use the PostgreSQL
datastore, so that incident and query-log history is durable by default rather
than relying on an opt-in that might be forgotten.

#### Acceptance Criteria
1. THE SYSTEM SHALL require a PostgreSQL connection (via `RCA_DATABASE_URL`) and SHALL use it as the backing store for incidents and the query log; there SHALL be no in-memory-only runtime mode in normal operation.
2. THE PostgreSQL driver (`psycopg` v3) SHALL be a core dependency installed in the base image (D2).
3. WHEN `RCA_DATABASE_URL` is not provided, THE SYSTEM SHALL fail fast at startup with a clear configuration error (rather than silently running without durability).
4. THE SYSTEM SHALL create the required tables/schema on first startup if they do not already exist (idempotent schema initialization).

### Requirement 5: Non-fatal on database failure

**User Story:** As an operator, I want the agent to keep diagnosing faults even
if the database is unavailable, so that persistence never reduces availability.

#### Acceptance Criteria
1. IF the database is unreachable at startup, THE SYSTEM SHALL retry with bounded backoff and log clearly; `/readyz` SHALL report not-ready until the DB connects (the DB is required, so readiness legitimately depends on it).
2. `/healthz` (liveness) SHALL NOT depend on the database, so a transient DB outage does not trigger a liveness-kill/restart loop.
3. IF a single persist (write) fails at runtime, THE SYSTEM SHALL log it and NOT crash the poll loop or the request; it SHALL keep the in-memory copy and repersist on the next mutation so memory and DB reconverge.
4. IF a transient DB outage occurs while running, THE SYSTEM SHALL continue serving reads from the in-memory cache and resume writes when the DB returns, without losing already-in-memory records.

### Requirement 6: Security of credentials and stored data

**User Story:** As a security reviewer, I want database credentials and stored
incident data handled safely, so that persistence does not weaken the agent's security posture.

#### Acceptance Criteria
1. THE PostgreSQL credentials SHALL be sourced from a Kubernetes Secret (Helm path) or an injected environment/secret (docker path); credentials SHALL NOT be hardcoded or committed.
2. THE stored incident data SHALL be treated as sensitive (it can contain real log lines and pod/object names); documentation SHALL state this.
3. THE connection SHOULD be restricted to the agent (e.g. ClusterIP service, network policy or same-namespace scope) rather than broadly exposed (confirm scope in Design).
4. THE agent's read-only-toward-Kubernetes posture SHALL remain unchanged; adding the datastore SHALL NOT introduce any Kubernetes write capability.

### Requirement 7: Consistent read contract

**User Story:** As a dashboard/API consumer, I want the same incident shapes
whether they come from memory or the database, so that nothing downstream changes.

#### Acceptance Criteria
1. THE `/incidents`, `/incidents/{id}`, and dashboard tab responses SHALL return the same field shapes regardless of whether an incident was freshly created or reloaded from PostgreSQL.
2. THE status filter semantics (`active` | `inactive` | `all`, newest first) SHALL be unchanged.
3. A reloaded incident served by `/incidents/{id}` SHALL be equivalent in its serialized shape to the same incident before a restart (round-trip fidelity).

### Requirement 8: Durable retention policy

**User Story:** As an operator, I want durable history to outlive the 200-item
in-memory cap, so that older incidents are not silently lost.

#### Acceptance Criteria
1. THE durable store SHALL NOT be limited to the in-memory `_MAX_STORED_INCIDENTS` (200) cap.
2. THE SYSTEM SHALL retain durable history for as long as the database lasts (D3): no application-level age/count pruning; the only bound is the PVC / host-volume disk capacity.
3. THE in-memory list MAY stay capped (200) for UI/performance while the database retains the full history; reads MAY page into the database beyond the in-memory cap.

### Requirement 9: Persist the runbook query log with responses

**User Story:** As an operator, I want every runbook query and its response
(hits) retained in the database, so that the history of what was asked and
whether it matched survives restarts and is available for later analysis.

#### Acceptance Criteria
1. WHEN a runbook-retrieval attempt is recorded via `QueryLog.record` (from `reasoning.steps.build_next_steps`), THE SYSTEM SHALL persist the entry to PostgreSQL.
2. THE persisted query-log entry SHALL include `timestamp`, `query`, `retriever`, `hit_count`, and `hit_titles` (the response/hits), round-tripping the full `QueryLogEntry` shape.
3. WHEN the agent starts with persistence configured, THE SYSTEM SHALL rehydrate the in-memory query log from PostgreSQL before serving `/runbook-queries`.
4. THE `GET /runbook-queries` response and its `stats()` (total / positive / negative counts) SHALL be unchanged in shape whether served from memory or rehydrated from the database.
5. WHEN `DELETE /runbook-queries` is called, THE SYSTEM SHALL clear BOTH the in-memory log and the persisted query-log rows (the clear is durable, not re-populated on next restart).
6. THE query log SHALL follow the same mandatory-datastore, non-fatal, and security rules as incidents (Requirements 4, 5, 6): persisted to the required DB, write failures logged and non-fatal, and the data treated as sensitive (queries may embed resource names).
7. THE durable query log SHALL NOT be limited to the in-memory `runbook_query_log_max_entries` cap and SHALL follow the durable retention policy (Requirement 8 / D3).

## Traceability to the confirmed defect

- The lost-history defect (clean restart wiped the in-memory store) is addressed
  primarily by Requirement 2 (persist) + Requirement 3 (rehydrate), with
  Requirement 1 providing the durable `db-pg` pod and Requirement 8 ensuring
  durable history is not capped at 200.
- The query-log loss (same in-memory `deque`, wiped on the same restart) is
  addressed by Requirement 9, reusing the opt-in/non-fatal/security/retention
  rules of Requirements 4, 5, 6, and 8.
- Backward-compat and availability are protected by Requirements 4 and 5.

## Notes

- Decisions D1-D6 are resolved above and reflected in Requirements 4, 5, and 8
  and in the Introduction invariant note (mandatory DB, no opt-in).
- Open point retained: whether to also back the existing `RCA_INCIDENT_CAPTURE_PATH`
  JSONL capture with the DB, or leave it as independent prior art (recommend leave as-is).
