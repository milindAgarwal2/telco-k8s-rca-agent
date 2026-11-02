#!/usr/bin/env bash
#
# deploy-cobra.sh — load & run the read-only rca-agent on the Cobra jumpserver,
# optionally with the local LLM rerank sidecar (llama.cpp serving a GGUF).
#
# Run this ON the Cobra jumpserver (s7427-Cobra-JS, 10.242.70.7) as user eagamil
# (uid/gid 1744, docker group), AFTER `oc login` (writes ~/.kube/config).
#
# READ-ONLY by construction: the agent only does get/list/watch. The optional
# LLM sidecar runs LOCALLY (loopback only, no internet, no public IP) and only
# re-ranks/explains hypotheses the deterministic pipeline already produced.
#
# Usage:
#   ./deploy-cobra.sh                 # agent only (extractive), verify+load+run+logs
#   ./deploy-cobra.sh --with-llm      # ALSO start the llama.cpp sidecar + enable LLM rerank
#   ./deploy-cobra.sh --with-llm --semantic  # ALSO enable the opt-in semantic
#       # runbook RAG (embeddings over uploaded runbooks). Needs the LLM sidecar
#       # (--with-llm) live; without it, falls back to the extractive retriever.
#   ./deploy-cobra.sh --no-logs       # don't tail logs at the end
#   ./deploy-cobra.sh --skip-verify   # skip sha256 verification (not recommended)
#
#   Pick exactly which images to use (tarballs must be present in this dir):
#   ./deploy-cobra.sh --app-tag 0.8.1                      # use rca-agent:0.8.1
#   ./deploy-cobra.sh --with-llm --app-tag 0.8.1 --sidecar-tag 0.8.0
#       # agent 0.8.1 + sidecar 0.8.0 (the agent and sidecar version often
#       #  differ — the sidecar changes far less often).
#   If --sidecar-tag is omitted with --with-llm, the NEWEST
#   rca-agent-sidecar-*.tar.gz present is auto-detected.
#
# Optional service-area impact mapping:
#   If ~/resilience_common_services_pod_mapping.xlsx exists on the jumpserver
#   (override with SERVICE_AREA_MAP_HOST=/path/to.xlsx), it is mounted read-only
#   and RCA_SERVICE_AREA_MAP_PATH is set, enabling the "Service area impacted"
#   panel on incidents. If absent, the feature stays inert and the agent runs
#   normally. Example:
#     SERVICE_AREA_MAP_HOST=~/resilience_common_services_pod_mapping.xlsx \
#       ./deploy-cobra.sh --with-llm --app-tag 0.9.0
#
# LLM sidecar prerequisites (only for --with-llm):
#   - the sidecar image tarball  (rca-agent-sidecar-<tag>.tar.gz) in this dir, AND
#   - the GGUF model file at $LLM_GGUF_HOST (default ~/models/model.gguf).
#   Copy the GGUF to the jumpserver ONCE, e.g.:
#     scp /home/milind/ChatBOT/models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
#         eagamil@10.242.70.7:~/models/model.gguf
#
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-rca-agent}"
IMAGE_TAG="${IMAGE_TAG:-0.8.1}"
CONTAINER_NAME="${CONTAINER_NAME:-rca-agent}"

# LLM sidecar config.
SIDECAR_IMAGE_NAME="${SIDECAR_IMAGE_NAME:-rca-agent-sidecar}"
# Empty = auto-detect the newest rca-agent-sidecar-*.tar.gz next to this script.
SIDECAR_IMAGE_TAG="${SIDECAR_IMAGE_TAG:-}"
SIDECAR_NAME="${SIDECAR_NAME:-rca-agent-llm}"
LLM_PORT="${LLM_PORT:-8090}"
LLM_GGUF_HOST="${LLM_GGUF_HOST:-$HOME/models/model.gguf}"

RCA_NAMESPACE="${RCA_NAMESPACE:-plantx2avzwcspgc-y-oc-consp-301}"
RCA_PORT="${RCA_PORT:-8004}"
RCA_NF_SELECTOR="${RCA_NF_SELECTOR:-}"
RCA_REASONING_MODE="${RCA_REASONING_MODE:-extractive}"
RUN_UID_GID="${RUN_UID_GID:-1744:1744}"
KUBECONFIG_HOST="${KUBECONFIG_HOST:-$HOME/.kube/config}"

# Optional service-area impact mapping workbook (read-only). When this file
# exists on the host it is mounted into the agent and RCA_SERVICE_AREA_MAP_PATH
# is set, enabling the "Service area impacted" panel. If absent, the feature
# stays inert and the agent runs normally.
SERVICE_AREA_MAP_HOST="${SERVICE_AREA_MAP_HOST:-$HOME/resilience_common_services_pod_mapping.xlsx}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKIP_VERIFY=0
TAIL_LOGS=1
WITH_LLM=0
WITH_SEMANTIC=0
# Flags: --app-tag <v> picks the agent image tag; --sidecar-tag <v> picks the
# LLM sidecar image tag (defaults to whatever sidecar tarball is present).
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-verify) SKIP_VERIFY=1 ;;
    --no-logs)     TAIL_LOGS=0 ;;
    --with-llm)    WITH_LLM=1 ;;
    --semantic)    WITH_SEMANTIC=1 ;;
    --app-tag)     IMAGE_TAG="$2"; shift ;;
    --app-tag=*)   IMAGE_TAG="${1#*=}" ;;
    --sidecar-tag)   SIDECAR_IMAGE_TAG="$2"; shift ;;
    --sidecar-tag=*) SIDECAR_IMAGE_TAG="${1#*=}" ;;
    -h|--help)     grep '^#' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "WARN: unknown arg '$1' (ignored)" >&2 ;;
  esac
  shift
done

# Auto-detect the sidecar tag from the newest tarball if not given explicitly.
if [ "$WITH_LLM" -eq 1 ] && [ -z "$SIDECAR_IMAGE_TAG" ]; then
  _sc="$(ls -1 "$SCRIPT_DIR"/rca-agent-sidecar-*.tar.gz 2>/dev/null | sort -V | tail -1 || true)"
  if [ -n "$_sc" ]; then
    SIDECAR_IMAGE_TAG="$(basename "$_sc" | sed -E 's/^rca-agent-sidecar-(.*)\.tar\.gz$/\1/')"
  fi
fi

# Derive refs + tarball paths AFTER tag selection.
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
SIDECAR_IMAGE_REF="${SIDECAR_IMAGE_NAME}:${SIDECAR_IMAGE_TAG}"
IMAGE_TARBALL="${IMAGE_TARBALL:-$SCRIPT_DIR/rca-agent-${IMAGE_TAG}.tar.gz}"
SHA_FILE="${SHA_FILE:-${IMAGE_TARBALL}.sha256}"
SIDECAR_TARBALL="${SIDECAR_TARBALL:-$SCRIPT_DIR/rca-agent-sidecar-${SIDECAR_IMAGE_TAG}.tar.gz}"

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not found on PATH."
docker info >/dev/null 2>&1 || die "cannot talk to the docker daemon (is '$USER' in the docker group?)."
[ -f "$IMAGE_TARBALL" ] || die "image tarball not found: $IMAGE_TARBALL"
[ -f "$KUBECONFIG_HOST" ] || die "kubeconfig not found at $KUBECONFIG_HOST. Run 'oc login ...' first."

# ---- checksum ---------------------------------------------------------------
if [ "$SKIP_VERIFY" -eq 0 ] && [ -f "$SHA_FILE" ]; then
  log "verifying sha256 of $(basename "$IMAGE_TARBALL") ..."
  ( cd "$(dirname "$IMAGE_TARBALL")" && sha256sum -c "$(basename "$SHA_FILE")" ) \
    || die "checksum verification FAILED — re-copy the tarball."
  log "checksum OK."
fi

# ---- load agent image -------------------------------------------------------
log "loading image $IMAGE_REF ..."
docker load -i "$IMAGE_TARBALL"
docker image inspect "$IMAGE_REF" >/dev/null 2>&1 || die "image $IMAGE_REF not present after load."

# ---- optional: LLM sidecar --------------------------------------------------
if [ "$WITH_LLM" -eq 1 ]; then
  [ -f "$SIDECAR_TARBALL" ] || die "sidecar image tarball not found: $SIDECAR_TARBALL (needed for --with-llm)."
  [ -f "$LLM_GGUF_HOST" ] || die "GGUF model not found at $LLM_GGUF_HOST. scp it there once (see --help)."
  log "loading sidecar image $SIDECAR_IMAGE_REF ..."
  docker load -i "$SIDECAR_TARBALL"
  docker image inspect "$SIDECAR_IMAGE_REF" >/dev/null 2>&1 || die "sidecar image not present after load."

  log "removing any existing sidecar '$SIDECAR_NAME' ..."
  docker rm -f "$SIDECAR_NAME" >/dev/null 2>&1 || true

  # LOOPBACK bind: on --network host, LLM_HOST=127.0.0.1 keeps the model
  # endpoint private to this host (not reachable by other jumpserver users).
  log "starting LLM sidecar '$SIDECAR_NAME' on 127.0.0.1:${LLM_PORT} (GGUF: $LLM_GGUF_HOST) ..."
  docker run -d \
    --name "$SIDECAR_NAME" \
    --restart unless-stopped \
    --network host \
    -e MODEL_PATH=/models/model.gguf \
    -e LLM_HOST=127.0.0.1 \
    -e LLM_PORT="$LLM_PORT" \
    -v "$LLM_GGUF_HOST":/models/model.gguf:ro \
    "$SIDECAR_IMAGE_REF"

  log "waiting for the LLM sidecar to answer on 127.0.0.1:${LLM_PORT} (model load can take ~10-30s) ..."
  llm_ok=0
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${LLM_PORT}/v1/models" >/dev/null 2>&1; then llm_ok=1; break; fi
    sleep 1
  done
  if [ "$llm_ok" -eq 1 ]; then
    log "LLM sidecar is up. Enabling LLM rerank in the agent."
    RCA_REASONING_MODE="llm"
  else
    err "LLM sidecar did not answer; recent logs:"
    docker logs --tail 30 "$SIDECAR_NAME" || true
    err "continuing with EXTRACTIVE mode (agent falls back safely)."
    RCA_REASONING_MODE="extractive"
  fi
fi

# ---- (re)start the agent ----------------------------------------------------
log "removing any existing container '$CONTAINER_NAME' ..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

# Optional service-area mapping: mount read-only + point the agent at it, but
# only if the workbook is present on the host (feature stays inert otherwise).
SERVICE_AREA_ARGS=()
if [ -f "$SERVICE_AREA_MAP_HOST" ]; then
  log "service-area map found ($SERVICE_AREA_MAP_HOST) -> enabling Service area impacted."
  SERVICE_AREA_ARGS=(
    -e RCA_SERVICE_AREA_MAP_PATH=/data/service-area-map.xlsx
    -v "$SERVICE_AREA_MAP_HOST":/data/service-area-map.xlsx:ro
  )
else
  log "no service-area map at $SERVICE_AREA_MAP_HOST (feature inert; agent runs normally)."
fi

# Semantic runbook RAG is OPT-IN and only meaningful with the LLM sidecar live
# (it synthesizes the retrieved hits). Enabled only when BOTH --semantic is
# passed AND reasoning_mode ended up "llm" (sidecar came up). Otherwise the
# agent falls back to the extractive retriever by construction.
RCA_SEMANTIC_FLAG="false"
if [ "$WITH_SEMANTIC" -eq 1 ]; then
  if [ "$RCA_REASONING_MODE" = "llm" ]; then
    log "semantic runbook RAG ENABLED (--semantic + LLM sidecar live)."
    RCA_SEMANTIC_FLAG="true"
  else
    err "--semantic requested but the LLM sidecar is not live; semantic RAG"
    err "needs the sidecar -> falling back to extractive retriever."
  fi
fi

log "starting $CONTAINER_NAME (ns=$RCA_NAMESPACE port=$RCA_PORT mode=$RCA_REASONING_MODE semantic=$RCA_SEMANTIC_FLAG) ..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --network host \
  --user "$RUN_UID_GID" \
  -e RCA_CLUSTER_ENABLED=true \
  -e RCA_KUBECONFIG_MODE=local \
  -e RCA_NAMESPACE="$RCA_NAMESPACE" \
  -e RCA_NF_SELECTOR="$RCA_NF_SELECTOR" \
  -e RCA_REASONING_MODE="$RCA_REASONING_MODE" \
  -e RCA_RUNBOOK_RAG_SEMANTIC="$RCA_SEMANTIC_FLAG" \
  -e RCA_LLM_BASE_URL="http://127.0.0.1:${LLM_PORT}" \
  -e RCA_PORT="$RCA_PORT" \
  -e KUBECONFIG=/kube/config \
  -e HOME=/tmp \
  "${SERVICE_AREA_ARGS[@]}" \
  -v "$KUBECONFIG_HOST":/kube/config:ro \
  "$IMAGE_REF"

# ---- health check -----------------------------------------------------------
log "waiting for the dashboard on port $RCA_PORT ..."
ok=0
for _ in $(seq 1 20); do
  if curl -fsS "http://localhost:${RCA_PORT}/healthz" >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if [ "$ok" -eq 1 ]; then
  log "dashboard is up: $(curl -fsS "http://localhost:${RCA_PORT}/healthz")"
  cat <<EOF

  OK rca-agent ${IMAGE_TAG} running (reasoning_mode=${RCA_REASONING_MODE}).
  Tunnel + view:  ssh -L ${RCA_PORT}:localhost:${RCA_PORT} eagamil@10.242.70.7
                  http://localhost:${RCA_PORT}/
  Manage:         docker logs -f ${CONTAINER_NAME}  |  docker rm -f ${CONTAINER_NAME}${WITH_LLM:+ ${SIDECAR_NAME}}
EOF
else
  err "dashboard did not come up on port ${RCA_PORT}. Recent logs:"
  docker logs --tail 40 "$CONTAINER_NAME" || true
  die "startup health check failed."
fi

if [ "$TAIL_LOGS" -eq 1 ]; then
  log "tailing agent logs (Ctrl-C to detach; container keeps running) ..."
  docker logs -f "$CONTAINER_NAME"
fi
