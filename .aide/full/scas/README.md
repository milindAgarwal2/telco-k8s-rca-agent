# SCAS MCP runtime

This is a reviewed snapshot of `framework-governance-agent` 0.5.0 for private
AIDE distributions. The SCAS source declares a proprietary license; keep this
runtime in an approved internal distribution. The full overlay copies it to
`.aide/full/scas` without adding dependencies to the application project.

From the target repository root, prepare the local runtime:

```powershell
uv sync --project .aide/full/scas --frozen
```

The build backend is pinned to `setuptools==84.0.0`; it must be present in the
configured package source or uv cache for the first preparation.

The workspace `scas` MCP runs `framework-governance-mcp` from that project with
`--offline --frozen`. Define `SCAS_REFRESH_TOKEN` in the process that starts
Kiro and approve that variable in Kiro's MCP Approved Env Vars setting. Do not
put its value in `mcp.json` or the SCAS configuration file. The server can list
tools and scan a local repository without contacting SCAS; component checks and
assessments need a valid token and network access.

Before an assessment, review
`.aide/full/scas/config/governance.scas.example.json` and provide that file
as the MCP tool's `config_path`. The server reads its own knowledge documents
from `.aide/full/scas/knowledge-base` through `SCAS_KNOWLEDGE_ROOT`. Assessment
reports are created only when those tools are called; use an output directory
under `.aide/local/` for disposable reports. Durable jobs use the dedicated
`.framework-governance/` directory, which the overlay adds to `.gitignore`.
