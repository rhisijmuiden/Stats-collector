#!/usr/bin/env bash
# Print release notes for a version from CHANGELOG.md and CHANGELOG.nl.md (Keep a Changelog format).
# Usage: scripts/release-notes.sh <section>   e.g. "Unreleased" or "0.1.0"
# The Dutch part follows an "<!-- nl -->" marker; the app shows it to Dutch users.
set -euo pipefail
SECTION="${1:?section required}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

extract() {
  awk -v want="$SECTION" '
    /^## \[/ { inside = (index($0, "[" want "]") > 0); next }
    inside { print }
  ' "$1"
}

extract "$ROOT/CHANGELOG.md"
if [ -f "$ROOT/CHANGELOG.nl.md" ]; then
  echo
  echo "<!-- nl -->"
  extract "$ROOT/CHANGELOG.nl.md"
fi
