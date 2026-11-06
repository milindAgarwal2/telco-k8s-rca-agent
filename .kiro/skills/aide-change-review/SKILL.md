---
name: aide-change-review
description: "Use when asked to review a diff, implementation, commit, pull request, or merge request against approved intent. Prioritizes evidence-backed correctness, contract, security, compatibility, operational, and verification findings without approving or merging."
---

# AIDE change review

Review the change against intended behavior and repository policy, not against
personal style preference.

## Procedure

1. Read applicable instructions and identify the approved requirements, design,
   tasks, and comparison base.
2. Inspect the complete relevant diff and enough surrounding source to verify
   behavior. Preserve unrelated user changes as context, not findings.
3. Trace changed behavior to requirements and tests.
4. Check for unintended scope, broken invariants, API or schema compatibility,
   error handling, concurrency, permissions, secret exposure, unsafe defaults,
   migration or rollback risk, observability, and operational consequences.
5. Confirm tests exercise the claimed behavior and failure mode. Note material
   checks that were skipped or cannot run locally.
6. For each finding, cite the smallest useful source location, explain the
   concrete impact, and suggest the smallest corrective direction.

## Finding priorities

- `P0`: immediate catastrophic or security-critical impact;
- `P1`: likely correctness, data, security, or availability failure;
- `P2`: meaningful defect or maintainability risk that should be fixed;
- `P3`: low-risk improvement that does not block the change.

Do not report speculation as a defect. If evidence is insufficient, label the
item as a question or verification gap.

## Output contract

Lead with findings in priority order. Then summarize requirement coverage,
tests and other evidence, checks not run, scope observations, and residual
risk. If there are no actionable findings, say so while still naming remaining
verification gaps.

Review may prepare a pull-request or merge-request summary when requested, but
it does not approve, merge, deploy, or claim human review.
