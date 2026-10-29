#!/usr/bin/env bash
#
# Single-process entrypoint: one uvicorn serves BOTH the read-only API and the
# server-rendered HTML dashboard on $RCA_PORT. (Before 0.5.0 this started two
# processes -- FastAPI on a Unix socket + Streamlit on the port -- which is no
# longer needed now the dashboard is plain FastAPI+Jinja2 in the same app.)
set -euo pipefail

exec uvicorn rca_agent.webhook.app:app \
    --host "${RCA_HOST:-0.0.0.0}" \
    --port "${RCA_PORT:-8080}" \
    --log-level "$(echo "${RCA_LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
