---
name: aide-approved-change-delivery
description: Run the approved-change workflow from context and specification through bounded implementation, evidence, and review.
---
# Approved change workflow

Follow `.aide/workflows/definitions/approved-change.md`. Use shared state and approval helpers; do not implement approval logic in this skill. Stop at specification approval, unresolved material findings, merge authorization, and deployment authorization.

For an explicit reusable BOS AIDE story/defect loop, load `bos-aide-loop`
and the supplied run definition. Use `loops/README.md` for its generic
inputs and plan/execute/resume examples. Reuse this workflow's specification,
approval, verification and review gates; the loop creates no second engine.
