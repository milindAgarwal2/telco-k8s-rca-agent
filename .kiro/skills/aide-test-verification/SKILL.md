---
name: aide-test-verification
description: "Use when asked to design, run, assess, or report verification for a requirement or change. Selects the cheapest sufficient mix of static, unit, contract, integration, end-to-end, and operational checks and reports passed, failed, skipped, and not-run evidence."
---

# AIDE test and verification

Verification proves observable behavior against requirements. Tool success is
not automatically product success.

## Procedure

1. Build a traceability list from requirement identifiers and failure modes to
   observable evidence.
2. Choose the cheapest level that catches each risk: static analysis, unit,
   contract, integration, end-to-end, or operational health.
3. Reuse existing test files, fixtures, and helpers before creating new ones.
4. Test public behavior and one intent per test. Include negative, boundary,
   compatibility, and recovery behavior where the risk warrants it.
5. Classify checks by execution needs: local, special hardware, network,
   credentials, lab, cluster, destructive fixture, or production-like target.
6. Obtain explicit authorization before contacting or changing an external
   target. Never substitute a production target for a missing fixture.
7. Preserve exact commands, relevant environment assumptions, and useful
   failure output.

## Evidence rules

- Linting and schema validation prove static properties only.
- A dry run proves request acceptance or rendering, not runtime behavior.
- A mocked test proves the modeled contract, not the external dependency.
- An operational health check must name the target, time, and observed signal.
- Model, accuracy, or performance changes require the repository-mandated
  evaluation or benchmark evidence.

## Output contract

Report a matrix with requirement or risk, check, environment, outcome, and
evidence. Outcomes are `PASSED`, `FAILED`, `SKIPPED`, or `NOT RUN`; never merge
skipped work into passed work. Summarize residual risk and the exact evidence
still needed for acceptance.
