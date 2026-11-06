# MCP builder skill specification

## Intent

Design and implement a minimal MCP integration only when an existing interface
cannot satisfy the validated user journey.

## Contract

The server has bounded typed tools, explicit mutation boundaries, secure
configuration, predictable errors, tests, and task-based evaluation. Existing
MCP configuration and troubleshooting are out of scope.

## Failure handling

Unavailable dependencies, invalid schemas, permission failures, timeouts, and
partial results must fail clearly without leaking secrets or switching targets.
