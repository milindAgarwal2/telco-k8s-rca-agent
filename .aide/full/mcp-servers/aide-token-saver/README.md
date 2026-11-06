# BOS AIDE Token Saver runtime

This workspace-scoped service provides bounded log views, exact raw recovery,
per-response-cycle metadata, and long-term aggregate metrics. It stores SQLite state
under `.aide/local/token-saver/`; the AIDE overlay ignores that directory.

The service never stores prompt text, response text, source code, tool arguments, or log
content. Token values are a UTF-8-byte proxy for the payloads the hooks can observe.
Native Kiro input/output tokens, credits, and cost remain unavailable and are reported as
`null` unless Kiro explicitly supplies structured usage values to a hook. Use
`aide-token-saver metrics --workspace . --days 90` for the local Kiro metrics report,
including model frequency, token-field coverage, response timing, and daily trends.

Run `aide-token-saver doctor --workspace .` after preparing the frozen runtime. Use
`aide-token-saver report --workspace . --days 30` for an easy-language outcome,
technique-level attempt counts, measured bounded-log token deltas, and chart-ready daily
trends. The report labels only positive measured log representation deltas as savings.
Focused retrieval and cache activity remain attempts or efficiency signals because no
comparable broad-read baseline or provider billing telemetry is available. Kiro renders
the supplied compatibility-focused Mermaid flowcharts and falls back to text bars when
Mermaid is unsupported.
