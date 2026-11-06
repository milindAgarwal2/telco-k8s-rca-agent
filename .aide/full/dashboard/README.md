# MACS BOS AIDE Metrics Dashboard

This Kiro/VS Code-compatible extension opens an editor-tab dashboard for the local
Full/Extended AIDE Token Saver and Kiro metrics collector. It makes no model calls,
starts no background service, and sends no metrics over the network. The extension
host invokes the already-installed workspace runtime through its isolated Python
environment and receives a content-free JSON snapshot. The webview displays only
those aggregates.

In Kiro, run **Extensions: Install from VSIX** and select
`.aide/full/dashboard/bos-aide-dashboard-0.1.3.vsix`, then run **BOS AIDE: Open Metrics
Dashboard** from the Command Palette. The extension also adds a status-bar shortcut.
The workspace must be trusted and the Full runtime environment must have been prepared
by installation verification. If the collector is unavailable, the dashboard labels
the last result stale instead of displaying it as current. **Run doctor** checks the
local collector and the dashboard reader and shows the result without opening a shell.
After Doctor, **Repair metrics** opens the installed Configuration Manager with this
workspace and Full flavor selected. Close Kiro, review and apply its plan, then reopen
Kiro. The explicit repair path verifies the reader and updates the matching VSIX.

The dashboard supports 7-, 30-, and 90-day views. It distinguishes observed local
activity, hook-supplied values, scoped token estimates, and unavailable official
credits. Kiro hook events do not guarantee provider token, model, or compaction
fields, so the dashboard shows field coverage and does not turn missing data into
zero. The 90-day SQLite state remains under `.aide/local/token-saver/` and is not
included in the VSIX or the AIDE overlay.
