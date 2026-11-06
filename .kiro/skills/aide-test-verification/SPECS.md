# Test and verification skill specification

## Intent

Select and report proportionate evidence that a change meets its requirements
and handles important failure modes.

## Contract

Verification traces to requirements, distinguishes test levels and target
needs, reuses nearby tests, and reports passed, failed, skipped, and not-run
checks separately.

## Failure handling

A failed test retains diagnostic output. Missing hardware, credentials, or an
authorized target produces an explicit evidence gap, never a false pass.
