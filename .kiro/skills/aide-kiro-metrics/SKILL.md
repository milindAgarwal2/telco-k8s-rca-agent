---
name: aide-kiro-metrics
description: Report locally observed Kiro model, token, compaction, timing, and usage metrics with explicit coverage and 90-day retention.
---

# Kiro metrics

Use this skill when the user asks which Kiro models are used, how many tokens were
consumed, how long responses took, whether context was compacted, or for usage trends.

Call `aide_kiro_metrics` once with a period from 1 to 90 days; use 90 when omitted.
The workspace collector is enabled by default in Full installations. The report is
metadata-only and local. State the number of completed responses and field coverage
alongside every token or model total. `unavailable` means Kiro did not provide that
field through the hooks; never infer it from prompt size, credits, or a model setting.

Present response latency and model distribution in a compact table. Use `daily` data
for a simple trend chart when useful. The `aide_log_savings_estimate` covers selected
log pages only; `provider_wide_tokens_saved` is unavailable. Never relabel a byte-based
estimate as provider usage or cost. Do not display or retain prompt or response content.
