#!/usr/bin/env bash
#
# git-push.sh — push (or fetch) through the Cloudflare Access gate in front of
# the internal GitLab that hosts this repo.
#
# WHY THIS EXISTS
#   gitlab.rosetta.ericssondevops.com sits behind Cloudflare Access (Zero-Trust
#   SSO). A normal `git push` gets HTTP-redirected to a Cloudflare login page and
#   fails with:
#       fatal: unable to update url base from redirection: ... cloudflareaccess.com ...
#
#   Two auth layers must be satisfied at the same time:
#     1. Cloudflare Access  -> a short-lived JWT sent as a `CF_Authorization` cookie
#     2. GitLab             -> your username + personal access token (basic auth)
#
#   This script fetches the current Access JWT via `cloudflared`, writes it into a
#   temporary Netscape cookie file, and runs git with `http.cookieFile` plus your
#   GitLab credentials so both layers pass.
#
# PREREQUISITES
#   - cloudflared installed (https://github.com/cloudflare/cloudflared)
#   - A one-time (per session/expiry) interactive login:
#         cloudflared access login "$REPO_URL"
#     The script will tell you to run this if no valid token is found.
#   - GitLab credentials available to git. Easiest is the credential store:
#         git config --global credential.helper store
#     with a line in ~/.git-credentials like:
#         https://<user>:<glpat-token>@gitlab.rosetta.ericssondevops.com
#     Alternatively export GITLAB_USER + GITLAB_TOKEN (see below). If neither is
#     found the script falls back to the user:token already embedded in the
#     repo's `origin` remote URL, if present.
#
# USAGE
#   scripts/git-push.sh                 # push current branch
#   scripts/git-push.sh main            # push an explicit branch/refspec
#   scripts/git-push.sh --fetch         # fetch instead of push (refreshes tracking)
#   scripts/git-push.sh -- --force-with-lease main   # pass extra args after `--`
#
# ENVIRONMENT OVERRIDES (optional)
#   GIT_HOST     default: gitlab.rosetta.ericssondevops.com
#   REPO_PATH    default: milind.agarwal/telco-k8s-rca-agent.git
#   GITLAB_USER  if set (with GITLAB_TOKEN) overrides credential lookup
#   GITLAB_TOKEN personal access token to pair with GITLAB_USER
#
set -euo pipefail

GIT_HOST="${GIT_HOST:-gitlab.rosetta.ericssondevops.com}"
REPO_PATH="${REPO_PATH:-milind.agarwal/telco-k8s-rca-agent.git}"
REPO_URL="https://${GIT_HOST}/${REPO_PATH}"

# ----- parse args ------------------------------------------------------------
ACTION="push"
EXTRA_ARGS=()
REFSPEC=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fetch)  ACTION="fetch"; shift ;;
    --push)   ACTION="push";  shift ;;
    --)       shift; EXTRA_ARGS+=("$@"); break ;;
    -h|--help)
      sed -n '2,46p' "$0"; exit 0 ;;
    *)        REFSPEC="$1";   shift ;;
  esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

command -v cloudflared >/dev/null 2>&1 || die "cloudflared not found on PATH."
command -v git         >/dev/null 2>&1 || die "git not found on PATH."

# ----- 1. obtain a valid Cloudflare Access token -----------------------------
CF_TOKEN="$(cloudflared access token --app "$REPO_URL" 2>/dev/null || true)"
if [[ -z "$CF_TOKEN" || "$CF_TOKEN" != eyJ* ]]; then
  cat >&2 <<EOF
No valid Cloudflare Access token for:
    $REPO_URL

Run the interactive login (opens a browser for SSO), then re-run this script:

    cloudflared access login "$REPO_URL"
EOF
  exit 1
fi

# ----- 2. resolve GitLab credentials -----------------------------------------
# Priority: explicit env vars -> ~/.git-credentials entry -> origin remote URL.
GL_CRED=""
if [[ -n "${GITLAB_USER:-}" && -n "${GITLAB_TOKEN:-}" ]]; then
  GL_CRED="${GITLAB_USER}:${GITLAB_TOKEN}"
elif [[ -f "$HOME/.git-credentials" ]] && grep -q "@${GIT_HOST}" "$HOME/.git-credentials" 2>/dev/null; then
  GL_CRED="$(grep "@${GIT_HOST}" "$HOME/.git-credentials" | head -n1 \
             | sed -E 's#https://([^@]+)@.*#\1#')"
else
  # Fall back to credentials embedded in the existing origin URL, if any.
  ORIGIN_URL="$(git remote get-url origin 2>/dev/null || true)"
  if [[ "$ORIGIN_URL" == *"@${GIT_HOST}"* ]]; then
    GL_CRED="$(printf '%s' "$ORIGIN_URL" | sed -E 's#https://([^@]+)@.*#\1#')"
  fi
fi
[[ -n "$GL_CRED" ]] || die "No GitLab credentials found. Set GITLAB_USER/GITLAB_TOKEN, add an entry for ${GIT_HOST} to ~/.git-credentials, or embed them in the origin URL."

PUSH_URL="https://${GL_CRED}@${GIT_HOST}/${REPO_PATH}"

# ----- 3. write a temp cookie file with the Access JWT -----------------------
COOKIE_JAR="$(mktemp "${TMPDIR:-/tmp}/cfcookie.XXXXXX")"
# Netscape cookie format: domain  flag  path  secure  expiry  name  value
printf '%s\tTRUE\t/\tTRUE\t0\tCF_Authorization\t%s\n' "$GIT_HOST" "$CF_TOKEN" > "$COOKIE_JAR"
chmod 600 "$COOKIE_JAR"
cleanup() { rm -f "$COOKIE_JAR"; }
trap cleanup EXIT INT TERM

# ----- 4. default refspec = current branch -----------------------------------
if [[ -z "$REFSPEC" ]]; then
  REFSPEC="$(git rev-parse --abbrev-ref HEAD)"
fi

# ----- 5. run git with the Access cookie + GitLab basic auth -----------------
echo ">> ${ACTION} ${REFSPEC}  (via Cloudflare Access + GitLab auth)"
git -c http.cookieFile="$COOKIE_JAR" "$ACTION" "$PUSH_URL" "$REFSPEC" "${EXTRA_ARGS[@]}"

# Keep the local remote-tracking ref aligned after a direct-URL push.
if [[ "$ACTION" == "push" ]]; then
  LOCAL_SHA="$(git rev-parse "$REFSPEC" 2>/dev/null || true)"
  if [[ -n "$LOCAL_SHA" ]]; then
    git update-ref "refs/remotes/origin/${REFSPEC}" "$LOCAL_SHA" 2>/dev/null || true
  fi
fi

echo ">> done."
