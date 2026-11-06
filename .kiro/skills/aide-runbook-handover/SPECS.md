# Runbook and handover skill specification

## Intent

Create operator-ready deployment, troubleshooting, rollback, recovery, and
handover instructions based on an approved change.

## Contract

Instructions identify targets, prerequisites, side effects, expected signals,
stop conditions, evidence capture, ownership, and safe rollback or recovery.
Secrets are named inputs, never embedded values.

## Failure handling

Unsafe or unverified rollback is labeled explicitly and replaced by an
escalation or approved recovery path. Documentation never claims execution.
