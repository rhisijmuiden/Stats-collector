#!/usr/bin/env bash
# Print release notes for a version from CHANGELOG.md (Keep a Changelog format, each entry followed by an
# indented "NL:" line with the Dutch translation; the app shows that line to Dutch users).
# Usage: scripts/release-notes.sh <section>   e.g. "Unreleased" or "0.1.0"
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
