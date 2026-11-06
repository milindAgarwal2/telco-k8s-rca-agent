# Installation and Operations

## Windows installation

```powershell
cd framework-governance-agent
.\scripts\setup.ps1
```

The script creates `.venv`, registers the local `src` directory without
downloading runtime dependencies and runs unit tests.

## Kiro verification

```powershell
.\scripts\start-kiro-scas.ps1
```

Paste the current SCAS refresh token into the secure prompt. Inside the Kiro
session:

```text
/mcp
```

Expected server: `framework-governance`.

The launcher keeps the refresh token only in the child process environment and
removes it when Kiro exits.

## Offline health check

```powershell
.\scripts\demo.ps1
```

Expected:

- exit code zero;
- five files under `reports\demo`;
- a mix of Green, Amber and Red sample findings.
- continuously refreshed percent, remaining count, current item and ETA.
- an offline HTML report with sortable columns and a pie chart that filters
  findings when its slices or legend are clicked.

## Long-running assessment operations

Start a background job:

```powershell
$Started = & ".venv\Scripts\python.exe" -m framework_governance start-job `
  --repo "C:\work\application" `
  --config "config\governance.scas.example.json" `
  --output "reports\application" | ConvertFrom-Json

& ".venv\Scripts\python.exe" -m framework_governance job-status `
  --job-id $Started.job_id --watch
```

The start result includes the component inventory and initial duration range.
The watcher continuously prints processed/total, remaining items, current
component/state, elapsed time, dynamic ETA and traffic-light counts.

Reconnect after closing Kiro or the terminal:

```powershell
& ".venv\Scripts\python.exe" -m framework_governance list-jobs
& ".venv\Scripts\python.exe" -m framework_governance job-status `
  --job-id <job-id> --watch
```

Persistent diagnostics are under
`.framework-governance\jobs\<job-id>\state.json` and `worker.log`. A running
job with heartbeat age above the configured stale threshold reports
`health=stale`; inspect the log and worker PID before deciding whether to
restart. Do not start a duplicate job merely because one status wait timed out.

Cancel cooperatively:

```powershell
& ".venv\Scripts\python.exe" -m framework_governance cancel-job `
  --job-id <job-id>
```

Cancellation is observed between component requests. An in-flight SCAS request
may run until the configured HTTP timeout before the worker becomes cancelled.

## Production configuration

1. Use `config/governance.scas.example.json`.
2. Confirm the endpoints against `SCAS-CONTRACT.md`.
3. Set `SCAS_REFRESH_TOKEN` or use `scripts/start-kiro-scas.ps1`.
4. Run `catalog-check` against a known available component.
5. Run an assessment against a non-sensitive pilot repository.
6. Review HTML and JSON outputs with the SCAS/3PPT owner.

Manual example:

```powershell
$env:SCAS_REFRESH_TOKEN = "<paste-current-refresh-token>"
.\.venv\Scripts\python.exe -m framework_governance catalog-check `
  --name Angular `
  --version 19.2.3 `
  --ecosystem npm `
  --config config\governance.scas.example.json
```

## Troubleshooting

| Symptom | Check |
|---|---|
| MCP server not listed | Run setup, verify `.venv\Scripts\python.exe`, inspect `/mcp` |
| All results Grey | SCAS network, refresh token, TLS trust, proxy and response contract |
| Token variable missing | Set `SCAS_REFRESH_TOKEN` before starting Kiro |
| HTTP 401 after retry | Generate/copy a new SCAS refresh token |
| Known component Red | Component-name alias or empty Search 3PP response |
| Version unresolved | Lockfile availability and detector support |
| HTML returns no records | Page is JavaScript-rendered or table headings differ |
| YAML config fails | Use JSON or install PyYAML |
| Kiro appears stuck | Ask it to get the job status; verify revision and heartbeat continue changing |
| Status wait timed out | This means no state change in that wait window; call it again with the same job ID |
| Job reports stale | Inspect the job's `worker.log`, PID, network and token validity |
| Kiro was restarted | Use `list_assessment_jobs`, then reconnect by job ID |

## Linux/macOS

Run `scripts/setup.sh`, then replace `.kiro/settings/mcp.json` with the contents
of `.kiro/settings/mcp.linux.example.json`.
