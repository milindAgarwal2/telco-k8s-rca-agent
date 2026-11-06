# AIDE Project Profile

## Identity

- Project name: `<required>`
- Repository root: `<required>`
- Selected revision: `<full immutable revision required>`
- Profile owner: `<required>`
- Last reviewed: `<YYYY-MM-DD>`

## Repository classification

- Primary languages and artifact types: `<required>`
- Application or service type: `<required>`
- Build/package systems: `<required>`
- Deployment or runtime environments: `<known facts or Unresolved>`

## Evidence authority

Document project-specific precedence. Suggested default:

1. Current source and schemas implement the present state.
2. Tests provide verification evidence for observed behaviour.
3. Reviewed specifications describe intended behaviour.
4. Generated drafts are candidates requiring review.
5. Relationship maps and derived graph views are navigation aids.

Disagreement rule: record the conflict, identify the owner, and stop any phase
whose correctness depends on an unresolved conflict.

## Knowledge locations

| Priority | Location | Status | Review owner |
| --- | --- | --- | --- |
| Primary | `<for example, knowledge-base/>` | `<reviewed/draft/mixed>` | `<owner>` |
| Secondary | `<for example, openwiki/>` | `<reviewed/draft/generated>` | `<owner>` |

## Validation commands

| Scope | Command | Preconditions | Side effects | Expected evidence |
| --- | --- | --- | --- | --- |
| Static | `<command>` | `<requirements>` | `<none/describe>` | `<result>` |
| Unit | `<command>` | `<requirements>` | `<none/describe>` | `<result>` |
| Integration | `<command>` | `<requirements>` | `<none/describe>` | `<result>` |

No command is approved merely because it appears in this table. Review its
contents and target before first execution in a new environment.

## Protected and excluded targets

- Files or folders that workflows may not modify: `<required>`
- Environments that workflows may not mutate: `<required>`
- Sensitive-data locations that must not be read or copied: `<required>`
- Commands that always require separate approval: `<required>`

## Approved integrations

| Integration | Purpose | Access mode | Credential owner | Failure behaviour |
| --- | --- | --- | --- | --- |
| `<name>` | `<purpose>` | `<read-only/mutating>` | `<human/system>` | `<stop/fallback>` |

Do not infer approval for an unlisted integration.

## Owners and review boundaries

- Specification approver: `<required>`
- Change owner: `<required>`
- Knowledge reviewer: `<required>`
- Operations/remediation approver: `<required or Not applicable>`
- Merge approver: `<required or Not applicable>`
- Deployment approver: `<required or Not applicable>`

## Unresolved setup questions

- `<question, evidence needed, and owner>`


