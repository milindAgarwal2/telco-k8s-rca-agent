# Bounded execution skill specification

## Intent

Implement a single approved task without expanding authority or disturbing
unrelated repository state.

## Contract

Execution is constrained by paths, tools, targets, iteration, approvals, and
verification. Results use `PASS`, `ESCALATE`, or `FAIL` and include complete
evidence and omissions.

## Failure handling

Invalid assumptions, missing approval, unavailable dependencies, or unsafe
scope expansion cause a safe stop. Existing files and external state are
preserved whenever the task cannot complete.
