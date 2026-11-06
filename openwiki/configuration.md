---
type: reference
title: Configuration Reference
description: Environment-driven settings (RCA_ prefix) controlling reasoning mode, cluster access, graph, detection, RAG, LLM, and incident capture.
tags:
  - configuration
  - settings
  - environment
  - reference
verified:
  - by: openwiki/0.4.3
    at: 2026-11-03T19:34:26.963Z
sources:
  - id: openwiki-source-7899632fc75fcc9c19586b6f
    resource: repo://docker/SIDECAR.md
  - id: openwiki-source-a0b9c504b0887690f38d5894
    resource: repo://src/rca_agent/config.py
  - id: openwiki-source-0cba96084ad97a9c0edf32a9
    resource: repo://src/rca_agent/graph/builder.py
generated: { by: "kiro", at: "2026-11-03T19:34:26.963Z" }
---

# Configuration Reference

> Draft pending subject-matter expert (SME) review.

All configuration is read from environment variables with the prefix `RCA_` (or
a local `.env` file). The single source of truth is the `Settings` class in
`src/rca_agent/config.py`. Defaults are chosen so the agent runs out of the box
in no-LLM extractive mode without a cluster connection.

## Defaults that make it run out of the box

Three defaults together let the agent run with nothing external:

- `reasoning_mode = "extractive"` - deterministic, no LLM, reproducible and cheap.
- `cluster_enabled = False` - graph and query tools use stubbed in-memory data.
- With the cluster disabled, the graph builder returns the demo graph.

## Settings by concern

All of the following are defined in `src/rca_agent/config.py`.

**Service.** `app_name`, `host` (default `0.0.0.0`), `port` (default `8080`),
`log_level` (default `INFO`).

**Reasoning mode.** `reasoning_mode` - `extractive` (default) or `llm`.

**Cluster access.** `cluster_enabled` (default `False`); `kubeconfig_mode`
(`auto`, `incluster`, or `local`); `namespace` (default `open5gs`);
`nf_selector` - a label selector scoping the monitored application (empty means
the whole namespace is one application).

**Graph.** `graph_rebuild_interval_seconds` (default 60);
`graph_history_window_minutes` (default 120).

**Event watcher.** `event_watch_enabled` (default `True`);
`event_watch_interval_seconds` (default 15); `event_max_age_minutes` (default
90) - the maximum age of a Kubernetes Warning event still worth acting on.

**Status-based detection.** `status_detection_enabled` (default `True`);
`status_unhealthy_rebuilds` (default 2) - a pod unhealthy across this many
consecutive rebuilds is raised even with no fresh event; 0 disables status-based
detection.

**Incident correlation.** `incident_correlation_window_minutes` (default 10) -
links incidents sharing an identical failure signature on a different resource.

**Evidence gathering.** `log_tail_lines` (default 200);
`change_correlation_window_minutes` (default 15); `prometheus_url` (optional) -
when unset, metrics are skipped gracefully and pod status, events, logs, and
changes still work.

**Runbook RAG.** `runbook_rag_url` (optional external doc-intelligence service,
still unbuilt); `runbook_rag_top_k` (default 3); `runbook_store_path`;
`runbook_asset_dir`.

**Semantic RAG (opt-in).** `runbook_rag_semantic` (default `False`);
`runbook_rag_embed_model` (default `BAAI/bge-small-en-v1.5`). Semantic mode is
gated: it is used only when the flag is on **and** the optional dependencies
import **and** the LLM sidecar is opted in and reachable; otherwise the agent
transparently falls back to the extractive keyword retriever.

**Service-area impact.** `service_area_map_path` (optional) - when set and the
file exists, incidents gain a `service_area` field; unset or missing leaves the
feature inert.

**LLM (only used when `reasoning_mode == "llm"`).** `llm_provider`, `llm_model`
(default `qwen2.5-1.5b-instruct`), `llm_base_url` (default
`http://127.0.0.1:8090`, loopback only), `llm_timeout_seconds` (default 30),
`llm_max_tokens` (default 512), `llm_temperature` (default 0.1). On any
error, timeout, or unavailable sidecar, reasoning falls back to the deterministic
extractive order, so enabling the LLM can never change which causes exist.

**Incident capture.** `incident_capture_path` (default empty/off),
`incident_capture_redact_logs`, `incident_capture_include_graph`,
`incident_capture_max_records` (default 5000), `incident_capture_graph_radius`.

## Sensitive setting: incident capture

The comment on `incident_capture_path` in `src/rca_agent/config.py` warns that
capture records include real log lines and object names from the monitored
namespace, so the capture file should be treated as sensitive. Setting
`incident_capture_redact_logs = true` drops log bodies while keeping reasons and
timestamps. Capture is off by default (empty path). Do not store the capture
file where untrusted parties can read it.

## Optional features and their safe fallbacks

Several settings gate optional behavior and fail safe when their prerequisites
are absent:

- Metrics are skipped if `prometheus_url` is unset.
- Semantic RAG falls back to extractive keyword retrieval unless all three gates
  hold.
- The service-area feature is inert unless the workbook path is set and present.
- The LLM rerank falls back to the extractive order on any sidecar failure.

## Related pages

- [Quickstart](/openwiki/quickstart.md)
- [Integrations and Data Inputs](/openwiki/integrations.md)
- [Operations and Deployment](/openwiki/operations-deploy.md)
- [Workflow: Fault Detection](/openwiki/workflow-detection.md)
