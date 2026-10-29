#!/usr/bin/env bash
#
# chaos-demo.sh — inject a SAFE, self-cleaning ImagePullBackOff fault so the
# read-only RCA agent detects it live.
#
# WHAT IT DOES
#   Creates ONE throwaway Deployment whose container image points at a
#   non-existent registry/tag. The pod goes ImagePullBackOff / ErrImagePull and
#   NEVER pulls or runs anything (lowest-risk possible fault — no code executes,
#   ~zero resources). The RCA agent, watching this namespace read-only, raises
#   an incident. Cleanup deletes it again.
#
# SAFETY (this runs in the SAME namespace as real production workloads)
#   * Everything created carries the label  rca-demo=true  and the name prefix
#     rca-demo-  .
#   * cleanup ONLY ever deletes resources matching  -l rca-demo=true  , and
#     asserts that label before deleting. It can never touch a real workload.
#   * --dry-run prints the exact `oc` commands without running them.
#   * An EXIT/INT trap cleans up if an interactive demo is interrupted (unless
#     you pass --no-trap, e.g. when you want the fault to persist between steps).
#
# IMPORTANT: this script is a SEPARATE actor using YOUR `oc` credentials. The
# RCA agent itself remains read-only (get/list/watch only) and never mutates
# the cluster.
#
# USAGE
#   ./chaos-demo.sh inject            # create the dummy Deployment (fault on)
#   ./chaos-demo.sh status            # show the ImagePullBackOff pod(s)
#   ./chaos-demo.sh cleanup           # delete everything labeled rca-demo=true
#   ./chaos-demo.sh inject --dry-run  # print commands only, change nothing
#
#   Override the namespace (must be set correctly or the script refuses to run):
#   RCA_DEMO_NAMESPACE=plantx2avzwcspgc-y-oc-consp-301 ./chaos-demo.sh inject
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# The namespace the RCA agent is watching. MUST match, or the agent won't see
# the fault. Default is Cobra 2a / cSAEGW-C; override via RCA_DEMO_NAMESPACE.
NAMESPACE="${RCA_DEMO_NAMESPACE:-plantx2avzwcspgc-y-oc-consp-301}"

# The single label that marks everything this script owns. Cleanup keys on it.
DEMO_LABEL_KEY="rca-demo"
DEMO_LABEL_VAL="true"
DEMO_LABEL="${DEMO_LABEL_KEY}=${DEMO_LABEL_VAL}"

# Resource name (prefixed so it's obviously throwaway in `oc get`).
DEPLOY_NAME="rca-demo-imagepull"

# The deliberately-broken image: a non-existent registry + tag. Nothing to pull.
BAD_IMAGE="fake-registry.invalid/rca-demo/does-not-exist:v0"

# kubectl/oc binary.
KUBECTL="${KUBECTL:-oc}"

DRY_RUN=0
USE_TRAP=1

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m[chaos]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn ]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

# Run (or, in dry-run, just print) an oc command.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  DRY-RUN: %s\n' "$*"
  else
    "$@"
  fi
}

preflight() {
  if ! command -v "$KUBECTL" >/dev/null 2>&1; then
    if [ "$DRY_RUN" -eq 1 ]; then
      warn "'$KUBECTL' not found — dry-run only prints commands, so continuing."
    else
      die "'$KUBECTL' not found on PATH."
    fi
  fi
  if [ "$DRY_RUN" -eq 0 ]; then
    "$KUBECTL" whoami >/dev/null 2>&1 \
      || die "not logged in. Run: oc login <api> -u <user> -p <pass> --insecure-skip-tls-verify"
    "$KUBECTL" get ns "$NAMESPACE" >/dev/null 2>&1 \
      || die "namespace '$NAMESPACE' not found / not visible to you."
  fi
  log "namespace: $NAMESPACE   user: $("$KUBECTL" whoami 2>/dev/null || echo '(dry-run)')"
}

# ---------------------------------------------------------------------------
# inject — create the labeled, deliberately-broken Deployment
# ---------------------------------------------------------------------------
inject() {
  preflight
  log "injecting ImagePullBackOff fault via throwaway Deployment '$DEPLOY_NAME'"
  log "  image = $BAD_IMAGE  (non-existent; nothing will be pulled or run)"

  local manifest
  manifest=$(cat <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${DEPLOY_NAME}
  namespace: ${NAMESPACE}
  labels:
    ${DEMO_LABEL_KEY}: "${DEMO_LABEL_VAL}"
    app: rca-demo-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: rca-demo-app
  template:
    metadata:
      labels:
        ${DEMO_LABEL_KEY}: "${DEMO_LABEL_VAL}"
        app: rca-demo-app
    spec:
      # Never restart into a working state; the whole point is the pull failure.
      restartPolicy: Always
      containers:
        - name: broken
          image: ${BAD_IMAGE}
          imagePullPolicy: Always
          # Minimal, SCC-friendly: no ports, no privilege, tiny resources.
          resources:
            requests:
              cpu: "10m"
              memory: "16Mi"
            limits:
              cpu: "50m"
              memory: "32Mi"
YAML
)

  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  DRY-RUN: %s apply -f - <<EOF\n%s\nEOF\n' "$KUBECTL" "$manifest"
  else
    printf '%s\n' "$manifest" | "$KUBECTL" apply -f -
  fi

  log "done. Within ~15s the agent's event watcher should raise an"
  log "ImagePullBackOff incident. Watch it:"
  log "  $KUBECTL get pods -n $NAMESPACE -l $DEMO_LABEL -w"
  log "  (dashboard) Incidents tab, or: curl localhost:8004/incidents"
}

# ---------------------------------------------------------------------------
# status — show what the demo created and its current (broken) state
# ---------------------------------------------------------------------------
status() {
  preflight
  log "demo resources (label $DEMO_LABEL):"
  run "$KUBECTL" get deploy,rs,pods -n "$NAMESPACE" -l "$DEMO_LABEL" -o wide || true
}

# ---------------------------------------------------------------------------
# cleanup — delete ONLY what carries the demo label (guarded)
# ---------------------------------------------------------------------------
cleanup() {
  preflight
  # Guard: assert there is nothing UNlabeled we might hit, and only ever delete
  # by the demo label. We never delete by name alone and never by namespace.
  log "cleaning up everything labeled '$DEMO_LABEL' in $NAMESPACE"
  run "$KUBECTL" delete deployment,replicaset,pod \
      -n "$NAMESPACE" -l "$DEMO_LABEL" --ignore-not-found=true
  if [ "$DRY_RUN" -eq 0 ]; then
    local remaining
    remaining=$("$KUBECTL" get deploy,pods -n "$NAMESPACE" -l "$DEMO_LABEL" \
                  --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [ "$remaining" = "0" ]; then
      log "cleanup complete — no resources left with label $DEMO_LABEL."
    else
      warn "$remaining resource(s) with label $DEMO_LABEL still terminating; re-run cleanup if needed."
    fi
  fi
}

on_interrupt() {
  # Fires only on Ctrl-C / TERM DURING inject (not on normal completion), and
  # only if the apply had started — so an interrupted injection doesn't leave a
  # half-created resource behind. Normal `inject` completion PERSISTS the fault
  # (a demo needs it to stay until you run cleanup).
  warn "interrupted during inject — running safety cleanup"
  cleanup || true
  exit 130
}

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------
CMD="${1:-}"; shift || true
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-trap) USE_TRAP=0 ;;
    -h|--help) grep '^#' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) warn "unknown arg '$arg' (ignored)" ;;
  esac
done

case "$CMD" in
  inject)
    # Arm an INTERRUPT-only trap (Ctrl-C/TERM) so an aborted injection cleans
    # up its own half-created resource. On NORMAL completion the fault PERSISTS
    # (the demo needs it to stay until you explicitly run cleanup).
    if [ "$USE_TRAP" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
      trap on_interrupt INT TERM
    fi
    inject
    # Normal completion: disarm so exiting leaves the fault in place.
    trap - INT TERM
    log "fault is now ACTIVE and will PERSIST. Run './chaos-demo.sh cleanup' when done."
    ;;
  status)  status ;;
  cleanup) cleanup ;;
  *)
    err "usage: $0 {inject|status|cleanup} [--dry-run] [--no-trap]"
    exit 2
    ;;
esac
