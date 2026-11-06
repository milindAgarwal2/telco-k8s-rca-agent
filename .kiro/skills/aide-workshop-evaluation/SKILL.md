---
name: aide-workshop-evaluation
description: "Use when asked to design, run, or report a controlled workshop comparison of AIDE-assisted and baseline work. Holds task, repository revision, model, tools, and environment constant and measures correctness, unnecessary changes, human corrections, verification gaps, time, and cost."
---

# AIDE workshop evaluation

Measure whether AIDE improves task outcomes, not whether participants like the
demo. Keep initial knowledge-ingestion effort separate from subsequent-task
performance.

## Study design

1. Define the evaluation question and decision threshold before collecting
   results.
2. Freeze the task text, acceptance criteria, repository revision, model and
   settings, available tools, hardware, time limit, and starting state.
3. Define baseline and AIDE conditions. The only planned difference should be
   the AIDE skills or knowledge intervention being evaluated.
4. Use representative tasks and include at least one failure or ambiguity case.
   Randomize or counterbalance order when learning effects are material.
5. Use the same objective verification harness and blinded human review where
   practical.
6. Record initial ingestion/setup time separately from per-task retrieval and
   execution time.

## Measures

- acceptance criteria satisfied;
- test and operational verification completeness;
- correctness defects and severity;
- unnecessary or out-of-scope changes;
- number and substance of human corrections;
- unsupported assumptions and verification gaps;
- elapsed time, model usage, tool calls, and estimated cost;
- escalation quality and safe-stop behavior.

Do not combine these into a single score unless the weighting is defined before
the study.

## Output contract

Produce the protocol, frozen inputs, condition matrix, raw result table,
reviewer rubric, deviations, metric calculations, qualitative findings,
limitations, and decision. Preserve failures and report missing telemetry as
missing, not zero.

Do not expose participant personal data, credentials, or proprietary prompts in
the report. Evaluation does not authorize changes to production systems.
