---
name: aide-operational-diagnosis-remediation
description: Collect observations and rank hypotheses, then keep remediation behind a separate explicit approval.
---
# Operational diagnosis and remediation workflow

Follow `.aide/workflows/definitions/diagnose-remediate.md`. Diagnosis uses approved read-only targets and produces timestamped evidence, relationships, hypotheses, and a proposal. Stop before any environment change; start a separately bound remediation plan only after explicit authorization.
