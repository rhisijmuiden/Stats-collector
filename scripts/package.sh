#!/usr/bin/env bash
# Build a release tarball: dist/stats-collector-<version>.tar.gz (+ .sha256)
# Usage: scripts/package.sh <version> <channel> [commit]
set -euo pipefail

VERSION="${1:?version required}"
CHANNEL="${2:?channel required (test|production)}"
COMMIT="${3:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
NAME="stats-collector-$VERSION"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  (cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)
fi

mkdir -p "$STAGE/$NAME" "$OUT"
cd "$ROOT"
tar --exclude='.venv' --exclude='__pycache__' --exclude='*.egg-info' --exclude='.pytest_cache' \
    --exclude='.ruff_cache' --exclude='*.db' --exclude='backend/var' \
    -cf - backend branding docs deploy scripts wordpress-plugin install.sh LICENSE README.md CHANGELOG.md \
  | tar -xf - -C "$STAGE/$NAME"
mkdir -p "$STAGE/$NAME/frontend"
cp -r frontend/dist "$STAGE/$NAME/frontend/dist"
echo "$VERSION" > "$STAGE/$NAME/VERSION"
cat > "$STAGE/$NAME/build.json" <<JSON
{"version": "$VERSION", "channel": "$CHANNEL", "commit": "$COMMIT", "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
JSON

tar -C "$STAGE" -czf "$OUT/$NAME.tar.gz" "$NAME"
(cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
echo "$OUT/$NAME.tar.gz"
