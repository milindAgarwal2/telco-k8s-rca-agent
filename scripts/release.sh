#!/usr/bin/env bash
#
# release.sh — one-command release: bump version -> test -> lint -> build image
#              -> package for Cobra (tarball + sha256 + deploy script + steps)
#              -> optionally scp to the jumpserver.
#
# Collapses the manual loop done by hand for 0.7.3 / 0.7.4 / 0.7.5.
#
# USAGE
#   scripts/release.sh 0.7.6              # bump to 0.7.6, test, build, package
#   scripts/release.sh 0.7.6 --scp        # ... and scp the package to Cobra
#   scripts/release.sh --no-bump          # use the CURRENT pyproject version
#   scripts/release.sh 0.7.6 --skip-tests # skip pytest/ruff (NOT recommended)
#   scripts/release.sh 0.7.6 --no-build   # bump + test only, no docker image
#
# ENV OVERRIDES
#   IMAGE_NAME   default: rca-agent
#   SCP_DEST     default: eagamil@10.242.70.7:~/
#   PY           default: .venv/bin/python
#
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-rca-agent}"
SCP_DEST="${SCP_DEST:-eagamil@10.242.70.7:~/}"
PY="${PY:-.venv/bin/python}"

DO_SCP=0; SKIP_TESTS=0; DO_BUILD=1; BUMP=1
VERSION=""

for arg in "$@"; do
  case "$arg" in
    --scp)        DO_SCP=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    --no-build)   DO_BUILD=0 ;;
    --no-bump)    BUMP=0 ;;
    -h|--help)    sed -n '2,24p' "$0"; exit 0 ;;
    -*)           echo "unknown flag: $arg" >&2; exit 2 ;;
    *)            VERSION="$arg" ;;
  esac
done

log()  { printf '\033[1;34m[release]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ----- 0. preflight ----------------------------------------------------------
[ -f pyproject.toml ] || die "run from the repo root (pyproject.toml not found)."
command -v docker >/dev/null 2>&1 || { [ "$DO_BUILD" -eq 0 ] || die "docker not found (needed to build the image)."; }

CUR_VERSION="$(grep -E '^version = ' pyproject.toml | sed -E 's/version = "(.*)"/\1/')"

# ----- 1. version bump -------------------------------------------------------
if [ "$BUMP" -eq 1 ]; then
  [ -n "$VERSION" ] || die "provide a version (e.g. 'scripts/release.sh 0.7.6') or pass --no-bump."
  log "bumping version $CUR_VERSION -> $VERSION"
  sed -i "s/^version = \"$CUR_VERSION\"/version = \"$VERSION\"/" pyproject.toml
  sed -i "s/__version__ = \"$CUR_VERSION\"/__version__ = \"$VERSION\"/" src/rca_agent/__init__.py
else
  VERSION="$CUR_VERSION"
  log "using current version $VERSION (no bump)"
fi

# verify the bump stuck
grep -q "^version = \"$VERSION\"" pyproject.toml || die "pyproject version not set to $VERSION"
grep -q "__version__ = \"$VERSION\"" src/rca_agent/__init__.py || die "__init__ version not set to $VERSION"

# ----- 2. test + lint --------------------------------------------------------
if [ "$SKIP_TESTS" -eq 0 ]; then
  log "running ruff ..."
  "$PY" -m ruff check . || die "ruff failed — fix before releasing."
  log "running pytest ..."
  "$PY" -m pytest -q || die "tests failed — fix before releasing."
  log "tests + lint OK."
else
  log "SKIPPING tests/lint (--skip-tests)."
fi

if [ "$DO_BUILD" -eq 0 ]; then
  log "done (--no-build): version $VERSION bumped, verified. No image built."
  exit 0
fi

# ----- 3. build the image ----------------------------------------------------
IMAGE_REF="${IMAGE_NAME}:${VERSION}"
log "building docker image $IMAGE_REF ..."
docker build -t "$IMAGE_REF" . >/dev/null || die "docker build failed."

# ----- 4. package for Cobra --------------------------------------------------
PKG_DIR="dist/cobra-package-${VERSION}"
mkdir -p "$PKG_DIR"
TARBALL="$PKG_DIR/${IMAGE_NAME}-${VERSION}.tar.gz"
log "saving image -> $TARBALL ..."
docker save "$IMAGE_REF" | gzip > "$TARBALL"
( cd "$PKG_DIR" && sha256sum "$(basename "$TARBALL")" > "$(basename "$TARBALL").sha256" )

# Carry forward the deploy script from the most recent prior package, bumping
# its default IMAGE_TAG to this version.
PREV_DEPLOY="$(ls -1 dist/cobra-package-*/deploy-cobra.sh 2>/dev/null | sort -V | tail -1 || true)"
if [ -n "$PREV_DEPLOY" ] && [ "$PREV_DEPLOY" != "$PKG_DIR/deploy-cobra.sh" ]; then
  cp "$PREV_DEPLOY" "$PKG_DIR/deploy-cobra.sh"
  sed -i -E "s/IMAGE_TAG:-[0-9]+\.[0-9]+\.[0-9]+/IMAGE_TAG:-${VERSION}/" "$PKG_DIR/deploy-cobra.sh"
  chmod +x "$PKG_DIR/deploy-cobra.sh"
  log "deploy-cobra.sh copied + IMAGE_TAG default set to $VERSION"
else
  log "WARN: no prior deploy-cobra.sh found to carry forward; add one to $PKG_DIR manually."
fi

log "package ready: $PKG_DIR"
ls -lh "$PKG_DIR"
log "sha256: $(cat "$TARBALL.sha256")"

# ----- 5. optional scp to Cobra ---------------------------------------------
if [ "$DO_SCP" -eq 1 ]; then
  log "scp -> $SCP_DEST ..."
  scp -p "$PKG_DIR"/* "$SCP_DEST" || die "scp failed."
  log "copied. Verify on the jumpserver:  sha256sum -c $(basename "$TARBALL").sha256"
fi

log "release $VERSION complete."
echo
echo "Next steps:"
echo "  git add -A && git commit -m \"$VERSION: ...\"  &&  ./scripts/git-push.sh"
[ "$DO_SCP" -eq 0 ] && echo "  (to deploy)  ./scripts/release.sh $VERSION --scp   # or scp $PKG_DIR/* $SCP_DEST"
echo "  (on jumpserver)  ./deploy-cobra.sh"
