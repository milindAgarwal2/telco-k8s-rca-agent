# Product and Technical Specification

## 1. Scope

### In scope

- Local repository inventory
- npm, Python, Maven/Gradle, NuGet, Go and OCI evidence
- SCAS refresh-token authentication and Search 3PP lookup
- File, generic JSON API and HTML-table lookup for offline/legacy use
- Configurable traffic-light policy
- CLI, Kiro custom agent and MCP usage
- Markdown, HTML, JSON, CSV and CycloneDX output
- Evidence, confidence and named decision rule
- Durable background assessment, live progress and reconnect

### Out of scope for v0.1

- Executing builds to resolve dependency graphs
- Downloading container images
- Vulnerability or license database enrichment
- Automatic source-code upgrades
- Browser-based SSO automation
- Writing approval decisions back to SCAS
- Direct search of Ericsson Maven repositories
- Direct search of Ericsson PyPI Artifactory/JFrog

## 2. Functional requirements

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-001 | Scan repository manifests | Supported files produce normalized components |
| FR-002 | Prefer resolved versions | Lockfile version replaces declared range |
| FR-003 | Retain evidence | Every component has at least one evidence path |
| FR-004 | Query SCAS | Search 3PP returns normalized component records |
| FR-005 | Apply policy | Every component receives exactly one status and rule |
| FR-006 | Isolate outages | SCAS failure produces Grey, not approval or denial |
| FR-007 | Generate reports | All five report artifacts are written |
| FR-008 | Support Kiro | Kiro can list and call MCP tools |
| FR-009 | Provide knowledge | HLD, LLD, specs and policy can be retrieved by MCP |
| FR-010 | Protect credentials | Tokens are taken from environment variables |
| FR-011 | Refresh authentication | Refresh token is exchanged for an access token |
| FR-012 | Search exact component | Name and version are sent as repeated SCAS filters |
| FR-013 | Find alternatives | Empty exact search falls back to name-only search |
| FR-014 | Project work | Start response lists item count, discovered categories and duration range |
| FR-015 | Expose live progress | State includes percent, processed/remaining counts, current item and status |
| FR-016 | Recalculate ETA | ETA changes from observed per-item durations throughout the job |
| FR-017 | Survive client interruption | Assessment continues if one MCP call or Kiro session ends |
| FR-018 | Reconnect | A later call can list jobs and resume status polling by job ID |
| FR-019 | Report health | Periodic heartbeat identifies healthy versus stale workers |
| FR-020 | Cancel safely | Cancellation is requested cooperatively and produces a terminal state |
| FR-021 | Resolve Maven names progressively | Search full coordinate, group prefix and exact group-leaf library in order |
| FR-022 | Preserve name-search evidence | Record the successful Maven lookup stage in catalog evidence |
| FR-023 | Honor Stako newer-version guidance | Every “newer version exists” finding is Amber and never Yellow/Red |
| FR-024 | Find partial Maven names | After exact leaf failure, search the group-leaf token with wildcards |
| FR-025 | Review partial candidates | Partial Maven candidates are Yellow and cannot become automatic Green |
| FR-026 | Whitelist internal OCI components | Approved Rosetta glob patterns are Green before catalog access |
| FR-027 | Sort HTML findings | Every HTML findings column supports ascending/descending mouse and keyboard sorting |
| FR-028 | Visualize HTML findings | Offline animated pie chart supports hover detail and click-to-filter |

## 3. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-001 | A scan must not execute repository code |
| NFR-002 | A repeated assessment against unchanged inputs must return the same statuses |
| NFR-003 | No source content may be included in a SCAS request |
| NFR-004 | The default source scan must be bounded at 5,000 files |
| NFR-005 | The package must run on Windows with Python 3.11+ |
| NFR-006 | Core runtime must have no mandatory third-party dependency |
| NFR-007 | Reports must remain readable when SCAS is unavailable |
| NFR-008 | Tokens must never appear in logs, reports or MCP results |
| NFR-009 | State writes must be atomic and revisions monotonically increasing |
| NFR-010 | No progress wait call may block for more than 25 seconds |
| NFR-011 | Heartbeat interval and stale threshold must be configurable |
| NFR-012 | HTML report interactivity must work without network/CDN dependencies |

## 4. MCP tool contracts

### `scan_repository`

Input:

```json
{
  "repository_path": "C:\\work\\application",
  "config_path": "config\\governance.example.json"
}
```

Output: `ScanResult` JSON containing repository, timestamp, components and warnings.

### `start_assessment_job` / `run_assessment`

Input:

```json
{
  "repository_path": "C:\\work\\application",
  "config_path": "config\\governance.scas.example.json",
  "output_directory": "reports\\application"
}
```

Output: job ID, persisted state location, inventory projection, initial ETA,
current progress and the next status action. The call does not wait for SCAS
lookups or report generation.

### `wait_for_assessment_update`

Input:

```json
{
  "job_id": "fg-20260725-140000-a1b2c3d4",
  "after_revision": 12,
  "timeout_seconds": 20
}
```

Output: the latest revision with status, health, phase, percent,
processed/remaining counts, current item/state, live ETA, status counts and
terminal report paths. A timeout is an unchanged-state response and never
restarts the assessment.

### `get_assessment_status`, `list_assessment_jobs`, `cancel_assessment_job`

These tools provide immediate reconnect, discovery and cooperative
cancellation using the durable job ID.

### `check_component`

Input:

```json
{
  "name": "Angular",
  "version": "19.2.3",
  "ecosystem": "npm",
  "config_path": "config\\governance.scas.example.json"
}
```

Output: one Finding.

## 5. Report schema

Top-level JSON fields:

- `assessment_version`
- `assessed_at`
- `repository`
- `catalog_mode`
- `policy_version`
- `compliance_score`
- `status_counts`
- `findings`
- `scan_warnings`
- `catalog_errors`

## 6. Acceptance scenario

Given the sample repository and sample catalog:

- Angular 19.2.3 is Green.
- RxJS 7.8.1 is Green.
- TypeScript 5.7.3 is Amber due to conditional status.
- Node 18 is Amber because SCAS contains another available version.
- Plotly.js is Red because it is not listed.
- all five report files are generated.

## 7. Future backlog

1. Run Maven/Gradle/npm/Python resolvers in opt-in sandbox mode.
2. Add SPDX and SARIF writers.
3. Add OSV/CVE, EOL and license-policy enrichment.
4. Add SCAS bulk-query API and persistent non-secret result cache.
5. Add signed report history and trend dashboard.
6. Add CI quality gates and pull-request annotations.
7. Add configurable alias registry outside source code.
8. Add an authenticated Ericsson Maven repository adapter.
9. Add an authenticated Ericsson PyPI Artifactory/JFrog adapter.
10. Define cross-catalog precedence, caching and provenance for SCAS plus
    internal artifact repositories before enabling either adapter.
