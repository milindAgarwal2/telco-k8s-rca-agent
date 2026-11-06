# AIDE Kiro Hook Runtime

This package provides deterministic support for eleven AIDE workspace hook
configurations. The full baseline installer places the runtime at
`.aide/full/hook/` and the reviewed configurations at `.kiro/hooks/`.
Installing the overlay does not approve a task or authorize an external
operation.

## Hook catalogue

| Hook | Main trigger | Purpose |
|---|---|---|
| `aide-approval-gate` | `PreToolUse` | Blocks protected actions without a matching current approval. |
| `aide-azure-observability` | `PreToolUse`, `PostToolUse` | Blocks direct Azure mutation patterns and records redacted read evidence. |
| `aide-azure-change-control` | `PreToolUse`, `PostToolUse` | Allows only the fixed change MCP, binds apply to a plan ID, and records redacted evidence. |
| `aide-safe-operation` | `PreToolUse` | Resolves operational targets and rejects unknown or unauthorized targets. |
| `aide-spec-readiness` | `PreTaskExec`, `PreToolUse` | Requires a reviewed normal or lightweight specification. |
| `aide-validate-change` | `PostToolUse` | Selects bounded local checks from changed artifact types. |
| `aide-task-evidence` | `PostToolUse`, `PostTaskExec`, `Stop` | Records redacted evidence with explicit status. |
| `aide-knowledge-drift` | `PostTaskExec` | Proposes knowledge updates without publishing them. |
| `aide-session-context` | `SessionStart` | Restores context without restoring execution authority. |
| `aide-record-human-decision` | `UserPromptSubmit` | Records explicit approve, reject, or revise declarations. |
| `aide-workflow-checkpoint` | `PostTaskExec`, `Stop` | Derives the pending workflow state from evidence. |
| `aide-story-lifecycle` | `PostFileCreate`, `PostFileSave` | Validates an imported Jira story and requests a bounded draft specification when it becomes EARS-ready. |

Only blocking pre-event handlers use exit code `2`. Other failures warn and
preserve current state.

## Prepare the runtime

From the target repository root:

```powershell
uv sync --project .aide/full/hook --all-groups --frozen
```

The full baseline installer already owns the hook configuration deployment.
Review `.kiro/hooks/` and `.aide/full/hook/policy.json` before use.

Initialize one ordinary specification workflow:

```powershell
uv run --project .aide/full/hook --offline --frozen aide-hook init `
  --task PROJECT-123 `
  --plan-revision r1 `
  --scope sample-capability `
  --spec-dir .kiro/specs/sample-capability `
  --target "file:src/**" `
  --target "file:tests/**" `
  --target "execution:workspace"
```

Initialize Jira story intake:

```powershell
uv run --project .aide/full/hook --offline --frozen aide-hook init-story `
  --jira-key PROJECT-123 `
  --story-path jira/PROJECT-123-sample-capability.md `
  --plan-revision r1
```

The Jira lifecycle validates the same local story after creation or save,
queues at most one idempotent specification request, limits repair attempts,
and stops at Gate A for human specification review.

## State and configuration

The default state directory is `.aide/full/hook/.state/`, which is excluded
from version control by the packaged runtime. Supported overrides are:

- `AIDE_HOOK_STATE_DIR` for an established local state directory;
- `AIDE_HOOK_POLICY` for a reviewed policy file; and
- `AIDE_WORKSPACE_ROOT` when Kiro does not launch from the repository root.

State writes use atomic replacement. Evidence logs are append-only and redact
secret-shaped keys and values. A corrupt or missing state file never becomes an
implicit approval.

## Verification

Run the packaged unit tests from the baseline source checkout:

```powershell
uv run --project catalog/flavors/full/runtimes/hook --offline --frozen `
  python -m unittest discover -s catalog/flavors/full/runtimes/hook/tests -v
```

For an installed overlay, verify that Kiro discovers all expected hook files,
the runtime resolves from `.aide/full/hook`, and protected operations remain
blocked until their exact task, revision, scope, gate, and target are approved.
