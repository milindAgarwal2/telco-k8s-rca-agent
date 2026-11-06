# Ansible content testing skill specification

## Intent

Create outcome-focused, idempotence-aware functional tests for Ansible content
with safe lifecycle cleanup.

## Contract

Tests trace to operational requirements, reuse existing Molecule scenarios,
support the approved container driver, and distinguish fixture results from live
target evidence.

## Failure handling

Scenario failure preserves diagnostic output and cleans only owned resources.
Missing tools or platforms are reported as not run.
