# AIDE Workflow Run Record

## Run identity

- Workflow ID: `<required>`
- Run ID: `<unique required>`
- Repository: `<required>`
- Selected revision or observation time: `<required>`
- Request or incident reference: `<required>`
- Started by: `<required>`
- Started at: `<ISO 8601 timestamp>`
- Current state: `<not-started/in-progress/waiting/blocked/completed/failed>`

## Scope

- Included targets: `<required>`
- Excluded targets: `<required>`
- Permitted tools/access: `<required>`
- Prohibited operations: `<required>`

## Phase ledger

| Phase | State | Inputs | Output/evidence | Decision owner | Timestamp |
| --- | --- | --- | --- | --- | --- |
| `<phase>` | `<state>` | `<references>` | `<references>` | `<owner>` | `<time>` |

## Claims

| Claim | Classification | Evidence | Confidence | Review state |
| --- | --- | --- | --- | --- |
| `<statement>` | `<fact/inference/hypothesis/decision>` | `<path, command, observation>` | `<high/medium/low>` | `<draft/reviewed/rejected>` |

## Gate decisions

| Gate | Exact subject/revision | Decision | Decided by | Timestamp | Conditions |
| --- | --- | --- | --- | --- | --- |
| `<gate>` | `<required>` | `<approved/rejected/pending>` | `<human>` | `<time>` | `<conditions>` |

Approval is valid only for the exact subject, scope, and revision recorded.
Substantive change invalidates the decision and returns the run to review.

## Verification and review

- Commands/checks executed: `<exact commands or Not executed>`
- Results: `<evidence references>`
- Independent review: `<reviewer and result>`
- Unverified areas: `<required when any>`
- Unresolved findings: `<required when any>`

## Resume or completion

- Last safe checkpoint: `<phase and artifacts>`
- Input required to resume: `<human decision or evidence>`
- Completion criteria met: `<yes/no with explanation>`
- Actions deliberately not taken: `<merge/deploy/publish/etc.>`


