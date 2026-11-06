---
name: aide-token
description: Show current AIDE Token Saver activation, per-response statistics, or an easy-language historical optimization report with compatible charts.
---

# AIDE Token Saver status and report

Use this skill when the user enters `/aide-token`, asks whether Token Saver is active,
requests current statistics, or asks for a report.

## Choose one bounded action

- For activation or the current response, call `aide_token_stats` once.
- For a historical report, call `aide_token_report` once with the requested period, or
  30 days when no period is supplied.
- If the MCP tool is unavailable, state that plainly and recommend running the AIDE
  updater. Do not invent values or retry repeatedly.

## Present the result

For status, say whether response hooks have observed activity and show the compact AIDE
statistics line. Explain that automatic collection and automatic optimization guidance
are active separately from provider billing telemetry.

For a historical report, lead with **What you gained**, then show the measured outcome
and optimization-technique table. Render each supplied chart value in its own fenced
Mermaid block. Use its text fallback if rendering fails. Treat activity as an attempt;
claim savings only for a positive measured bounded-log representation delta.

Always state that provider-wide tokens and monetary savings are unavailable unless the
provider supplies those measurements. Do not expose or retain prompt, response, source,
tool payload, or log content.
