# GitOps cluster debugging skill specification

## Intent

Diagnose live Flux reconciliation failures through an existing approved
`flux-operator-mcp` integration.

## Contract

Activation requires an explicit target, authorization, source revision, and
available integration. Diagnosis is evidence-based; mutation is separately
approved; success includes runtime reconciliation and workload evidence.

## Failure handling

Missing prerequisites or provider loss stops the workflow without switching
tools or targets and without altering desired or live state.
