# Low-Level Design

## 1. Package responsibilities

| Module | Main types/functions |
|---|---|
| `models.py` | Component, CatalogRecord, Finding, ScanResult, Assessment |
| `config.py` | Default configuration, deep merge and path resolution |
| `scanner.py` | RepositoryScanner and ecosystem parsers |
| `catalog.py` | ScasTokenProvider, ScasCatalogAdapter and legacy catalog adapters |
| `policy.py` | PolicyEngine and deterministic status rules |
| `report.py` | ReportWriter and CycloneDX generation |
| `service.py` | GovernanceService orchestration façade |
| `jobs.py` | JobManager, projection model and atomic progress state |
| `job_worker.py` | Detached assessment process and terminal-state handling |
| `cli.py` | Command-line interface |
| `mcp_server.py` | MCP JSON-RPC protocol and safe tools |

## 2. Scan sequence

```mermaid
sequenceDiagram
    participant K as Kiro
    participant M as MCP
    participant S as Scanner
    participant C as SCAS
    participant P as Policy
    participant R as Reports
    participant J as Job state
    participant W as Worker
    K->>M: start_assessment_job
    M->>S: scan repository
    S-->>M: normalized inventory
    M->>J: persist projection, plan and queued state
    M->>W: launch detached worker
    M-->>K: job ID, inventory and initial ETA
    loop Each component
        W->>J: current item = querying SCAS
        W->>C: refresh token if needed; search name/version
        C-->>W: catalog records or error
        W->>P: evaluate evidence and records
        P-->>W: finding and rule
        W->>J: processed count, status and recalculated ETA
        K->>M: wait_for_assessment_update
        M->>J: read state after revision
        M-->>K: compact live update
    end
    W->>R: write all formats
    W->>J: completed and report paths
    M-->>K: terminal update
```

## 3. Component model

`Component` contains:

- canonical name;
- detected version or null;
- ecosystem;
- category;
- source and scope;
- confidence;
- one or more evidence paths;
- optional Package URL.

The merge key is normalized `(ecosystem, name)`. When duplicate evidence exists,
the resolved dependency version wins over direct, development and source-only
evidence in that order.

## 4. Detector behavior

### npm

- `package.json` supplies direct and development dependencies and Node engine.
- `package-lock.json` supplies resolved package versions.
- Known packages are canonicalized, for example `@angular/core` to Angular.

### Python

- `requirements.txt` parses common version constraints.
- `pyproject.toml` parses PEP 621 dependencies and Python runtime requirement.

### Maven and Gradle

- Maven XML dependencies and parent Spring Boot version are read.
- Simple Maven property references are resolved.
- Gradle string coordinates and Spring Boot plugin versions are recognized.

### .NET, Go and OCI

- `.csproj` package references and target frameworks are read.
- `go.mod` runtime and required modules are read.
- Dockerfile/Containerfile `FROM` images are read without pulling images.

### Source evidence

Known import patterns can detect frameworks missing from manifests. These
records have confidence `0.6` and an unresolved version. The configurable scan
cap defaults to 5,000 source files.

## 5. Catalog behavior

### File

Reads an approved JSON snapshot. This is the test and offline baseline.

### SCAS Search 3PP

`ScasTokenProvider` sends
`refresh_token=<value>` as `application/x-www-form-urlencoded` to
`/registry/auth/token/refresh`. It caches `access_token` in memory until thirty
seconds before `expires_in`.

`ScasCatalogAdapter` calls `/ordering/components/search` using repeated filter
parameters:

```text
filter=compName,likei,*<name>*
filter=compVersion,NTXEQ,<version>
```

At each name stage, an empty exact-version search is followed by a name-only
search. Maven coordinates add these ordered stages:

1. full coordinate, for example `com.itextpdf:io`;
2. group prefix before `:`, for example `com.itextpdf`;
3. exact group-leaf library name without wildcard, for example `itextpdf`.
4. partial group-leaf library name, for example `*itextpdf*`.

The next stage runs only when the previous stage returns no matching component.
The final partial stage accepts the token anywhere in the primary SCAS name and
changes an otherwise approved response to review evidence. Policy therefore
returns Yellow with rule `PARTIAL-NAME-MATCH`.
The adapter accepts Spring-style `content` pagination and maps `compName` and
`compVersion`. The successful stage is retained in raw evidence as
`_governance_search_match`.
HTTP 401 forces one token refresh and one retry.

### Generic API

The earlier generic GET adapter remains available for non-SCAS catalogs.

### HTML

Fetches a configured search URL and parses ordinary HTML tables. This is a
compatibility adapter; SCAS REST mode is preferred.

## 6. Policy algorithm

Evaluation order is significant:

1. Component matches an approved whitelist pattern → Green without SCAS lookup.
2. Catalog error → Grey.
3. No component match → configured unknown-component status, default Red.
4. Stako comment says a newer version exists → Amber; never Yellow or Red.
5. Exact version with denied status → Red.
6. Exact version with approved status → Green.
7. Exact version with conditional status → Amber.
8. Partial/review name match → Yellow.
9. Unresolved detected version → Yellow.
10. Component match without exact version → Amber when a target exists, otherwise Yellow.
11. Remaining ambiguous status → Yellow.

### HTML report behavior

The report embeds all CSS and JavaScript and has no CDN dependency. Column
headers sort findings in ascending/descending order by mouse or keyboard. A
canvas pie chart animates on load, exposes hover counts/percentages and filters
table rows when a slice or legend item is selected.

Every branch emits a stable `policy_rule`.

## 7. Durable job lifecycle

Each job is stored under:

```text
.framework-governance/jobs/<job-id>/
  plan.json
  state.json
  worker.log
  cancel.requested   # present only after cancellation request
```

`state.json` is replaced atomically. Its monotonically increasing `revision`
allows long polling without losing an update. A heartbeat updates the file at
the configured interval even while one SCAS HTTP request is in progress.

Initial expected duration is:

```text
inventory time + (item count × configured seconds/item) + report overhead
```

After an item completes, its duration updates an exponential moving average:

```text
EMA = 0.3 × latest duration + 0.7 × previous EMA
ETA = remaining items × EMA + report overhead
```

Terminal states are `completed`, `failed` and `cancelled`. A heartbeat older
than `stale_after_seconds` is reported as unhealthy, while the job data and log
remain available for diagnosis.

## 8. MCP protocol

The server accepts newline-delimited JSON-RPC 2.0 over stdin/stdout and supports:

- `initialize`
- `ping`
- `tools/list`
- `tools/call`

Exposed tools:

| Tool | Mutation |
|---|---|
| `scan_repository` | None |
| `check_component` | None |
| `get_knowledge_document` | None |
| `start_assessment_job` | Writes job state and caller-selected reports |
| `run_assessment` | Nonblocking alias for `start_assessment_job` |
| `get_assessment_status` | None |
| `wait_for_assessment_update` | None |
| `list_assessment_jobs` | None |
| `cancel_assessment_job` | Writes a cooperative cancellation marker |

## 9. Error handling

- Invalid repository/configuration is a tool or CLI error.
- A per-component SCAS failure becomes a Grey finding and is recorded.
- Authentication errors never include the refresh or access token.
- Manifest parse failures become scan warnings and do not abort other detectors.
- Reports are generated even when some findings are Grey.
- Worker exceptions produce a failed terminal state and traceback in
  `worker.log`; tokens are not included.
- Kiro/MCP disconnection does not alter the detached worker.
