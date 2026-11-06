---
type: workflow
title: Testing and Evaluation
description: The pytest unit suite and the offline fault-injection harness that measures top-2 accuracy.
tags:
  - testing
  - evaluation
  - pytest
  - accuracy
  - fault-injection
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
  - id: openwiki-source-7ca1f0da91c7b4c2e9da3b80
    resource: repo://src/rca_agent/eval/README.md
  - id: openwiki-source-0c4ebc2be8896f93b0311227
    resource: repo://src/rca_agent/eval/runner.py
  - id: openwiki-source-8fae5c4c3525e94907672129
    resource: repo://src/rca_agent/eval/scorer.py
  - id: openwiki-source-6aaab79bd869ffec46a18c13
    resource: repo://tests/test_anchor_phase1.py
  - id: openwiki-source-502c5a8ec75087e62a5f761a
    resource: repo://tests/test_cluster_graph.py
  - id: openwiki-source-28ae127d14a9e73ad2bfdc74
    resource: repo://tests/test_event_watcher.py
  - id: openwiki-source-c04816b162233aeb0c9eb28d
    resource: repo://tests/test_runbook_rag.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Testing and Evaluation

> Draft pending subject-matter expert (SME) review.

The project separates two kinds of checks: the pytest unit suite (verification
that components behave as written) and the fault-injection harness (measurement
of how accurately the agent names the right root cause).

## Commands

From the `Makefile`:

- `make test` - run the full pytest suite (`.venv/bin/python -m pytest -q`).
- `make lint` - Ruff static checks.
- `make check` - lint plus test (the pre-commit gate).
- `make eval` - run the fault-injection accuracy harness
  (`.venv/bin/python -m rca_agent.eval`).

The eval harness can also be run directly: `python -m rca_agent.eval`
(`--no-write` to just print, `--min-top2 0.9` to fail if top-2 accuracy drops
below 90%), per `src/rca_agent/eval/README.md`.

## Unit test coverage (verification)

The `tests/` directory covers the major subsystems. Representative modules:

- `test_cluster_graph.py`, `test_reasoning.py` - graph building and the
  extractive reasoning pipeline.
- `test_event_watcher.py`, `test_webhook.py` - automatic detection and the
  Alertmanager webhook.
- `test_runbook_rag.py`, `test_semantic_rag.py`, `test_runbook_synth.py`,
  `test_llm_rerank.py` - runbook retrieval, semantic RAG, synthesis, and LLM
  rerank.
- `test_impact_loader.py`, `test_impact_pipeline.py` - the service-area impact
  workbook and pipeline.
- `test_anchor_phase1.py`, `test_anchor_phase2.py`, `test_anchor_phase3.py` -
  service-anchored incident resolution.
- `test_pptx_report.py`, `test_gui_service_area.py`,
  `test_gui_incident_0_7_1.py`, `test_ascii_safety.py` - the PPTX export, the
  dashboard, and ASCII safety.

These are verification evidence: they assert that the code does what the source
describes.

## The fault-injection harness (accuracy measurement)

`src/rca_agent/eval/` is a synthetic, offline, cluster-free benchmark. Per its
`README.md`, it injects a known fault into a fake Kubernetes cluster, runs the
**real** extractive reasoning pipeline over it, and measures whether the agent's
ranked hypotheses name the correct root cause.

- `fake_cluster.py` - a package-local, duck-typed read-only kube client, with no
  `kubernetes` package dependency.
- `cases.py` - the `FaultCase` model and the `FAULT_LIBRARY`. Each case builds a
  store with one injected fault, the triggering alert, and a `ground_truth`
  matcher that recognizes the correct cause.
- `runner.py` - for each case, builds a real `GraphBuilder` over the fake client
  with `cluster_enabled=True` and `reasoning_mode="extractive"`, runs the real
  `ReasoningFlow`, and scores the result. The runner never crashes on a single
  case; an exception is captured as a per-case error.
- `scorer.py` - computes top-1, top-2, and the 1-based matched rank.
- `report.py` and `__main__.py` - the Markdown/CSV table and the command-line
  interface.

### Headline metric: top-2 accuracy

Per `src/rca_agent/eval/scorer.py` and the eval `README.md`, a case is correct
when the known root cause appears in the **top 2** ranked hypotheses. Top-1 and
the exact rank are also reported for diagnostics. The eval README explains that
top-2 is the operationally meaningful bar because the agent surfaces a short
ranked list for a human, and it tolerates the honest case where a self-contained
probe failure and its underlying cause both legitimately appear.

### Fault library

The eval `README.md` lists eight cases: OOMKilled, CrashLoopBackOff,
ImagePullBackOff, readiness-probe failure (HTTP 500), a bad mounted-ConfigMap
change, an unhealthy upstream cascade via a `calls` edge, node NotReady, and two
simultaneous independent faults. The README is explicit that this synthetic
benchmark is not a substitute for live-cluster validation, and that live chaos
injection is deliberately out of scope.

## Related pages

- [System Overview](/openwiki/overview.md)
- [Reasoning: Extractive Pipeline and LLM Rerank](/openwiki/reasoning-pipeline.md)
- [Workflow: Fault Detection](/openwiki/workflow-detection.md)
- [Quickstart](/openwiki/quickstart.md)
