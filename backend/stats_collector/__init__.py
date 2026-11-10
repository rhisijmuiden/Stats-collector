"""Stats Collector: self-hosted statistics and reporting platform."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Release root (contains VERSION, build.json, branding/, docs/, frontend/dist). The package is installed
# in editable mode inside each release, so this resolves to /opt/stats-collector/releases/<version>.
APP_ROOT = Path(os.environ.get("SC_APP_ROOT") or Path(__file__).resolve().parent.parent.parent)
_ROOT = APP_ROOT


def _read_version() -> str:
    for candidate in (_ROOT / "VERSION", Path(__file__).resolve().parent / "VERSION"):
        if candidate.is_file():
            return candidate.read_text().strip()
    return "0.0.0"


def build_info() -> dict:
    """Build metadata written by the release workflow (build.json in the release root)."""
    info = {"version": _read_version(), "commit": None, "channel": None, "built_at": None}
    path = _ROOT / "build.json"
    if path.is_file():
        try:
            info.update(json.loads(path.read_text()))
        except (OSError, ValueError):
            pass
    return info


__version__ = _read_version()
