#!/usr/bin/env bash
#
# Starts the FastAPI backend on a Unix domain socket (NOT a TCP port -- see
# below), then the Streamlit dashboard, which binds $RCA_PORT directly. That
# is the ONLY network port this container ever opens.
#
# Why a socket and not 127.0.0.1:<port>: this image is run with
# `--network host` (see deploy-cobra.sh), which shares the host's network
# namespace -- a "127.0.0.1-only" TCP port would still be reachable by every
# OTHER process on that shared jumpserver, not just this container. A Unix
# socket is a path in this container's own filesystem namespace instead,
# which `--network host` does NOT share, so nothing outside this container
# can reach it, same-host or not.
#
# Deliberately fails loudly: if EITHER process dies, this script tears down
# the other and exits non-zero, so `docker ps`/`docker logs` shows a stopped
# container instead of silently serving a half-broken app.
set -euo pipefail

UDS_PATH="/tmp/rca-agent.sock"
rm -f "$UDS_PATH"

uvicorn rca_agent.webhook.app:app --uds "$UDS_PATH" \
    --log-level "$(echo "${RCA_LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')" &
FASTAPI_PID=$!

RCA_BACKEND_UDS="$UDS_PATH" streamlit run /app/streamlit_app/dashboard.py \
    --server.address=0.0.0.0 \
    --server.port="${RCA_PORT:-8080}" \
    --server.headless=true \
    --browser.gatherUsageStats=false &
STREAMLIT_PID=$!

terminate() {
    kill "$FASTAPI_PID" "$STREAMLIT_PID" 2>/dev/null || true
}
trap terminate TERM INT

# Exit as soon as EITHER process dies -- see header comment above.
wait -n "$FASTAPI_PID" "$STREAMLIT_PID"
terminate
wait
