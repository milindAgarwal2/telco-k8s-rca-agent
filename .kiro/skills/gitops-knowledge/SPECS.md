# GitOps knowledge skill specification

## Intent

Provide repository-aware Flux concepts and manifest guidance without requiring
live-cluster access.

## Contract

Guidance derives controller APIs and repository patterns from evidence, explains
reconciliation and dependency behavior, protects secret boundaries, and does
not claim runtime state from static validation.

## Failure handling

Unknown installed versions or controller capabilities are reported as
compatibility questions rather than assumed.
