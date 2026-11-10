"""Release discovery on GitHub for the production and test channels, and release-note parsing."""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field

import httpx
from packaging.version import InvalidVersion, Version

from .. import build_info
from ..config import get_settings

CHANNELS = ("production", "test")
SECTION_MAP = {
    "added": "added",
    "new": "added",
    "changed": "changed",
    "deprecated": "changed",
    "removed": "removed",
    "fixed": "fixed",
    "security": "fixed",
}
TAG_RE = re.compile(r"^v?(\d+\.\d+\.\d+(?:-(?:rc|test)\.\d+)?)$")


@dataclass
class Release:
    version: str
    tag: str
    channel: str  # production | test
    name: str
    published_at: str | None
    url: str
    notes: dict[str, dict[str, list[str]]] = field(default_factory=dict)  # lang -> section -> items
    asset_url: str | None = None
    checksum_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_version(value: str) -> Version | None:
    try:
        return Version(value.removeprefix("v"))
    except InvalidVersion:
        return None


def parse_notes(markdown: str) -> dict[str, dict[str, list[str]]]:
    """Split Keep-a-Changelog markdown into added/changed/removed/fixed lists, in English and Dutch.

    Each bullet may be followed by an indented ``NL: ...`` line with the Dutch translation; without it the
    English text is used for Dutch too.
    """
    empty = {"added": [], "changed": [], "removed": [], "fixed": []}
    notes: dict[str, dict[str, list[str]]] = {"en": {k: [] for k in empty}, "nl": {k: [] for k in empty}}
    current: str | None = None
    for raw in markdown.splitlines():
        line = raw.strip()
        heading = re.match(r"^#{2,4}\s+(.+?)\s*$", line)
        if heading:
            current = SECTION_MAP.get(heading.group(1).strip().lower())
            continue
        if not current:
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet and not raw.startswith((" ", "\t")):
            notes["en"][current].append(bullet.group(1))
            notes["nl"][current].append(bullet.group(1))
        elif line.startswith("NL:") and notes["en"][current]:
            notes["nl"][current][-1] = line[3:].strip()
        elif line and notes["en"][current] and raw.startswith(("  ", "\t")):
            notes["en"][current][-1] += " " + line
            if notes["nl"][current][-1] != notes["en"][current][-1]:
                notes["nl"][current][-1] += " " + line
    return notes


def split_languages(body: str) -> dict[str, dict[str, list[str]]]:
    return parse_notes(body or "")


def release_from_github(item: dict) -> Release | None:
    if item.get("draft"):
        return None
    match = TAG_RE.match(item.get("tag_name", ""))
    if not match:
        return None
    version = match.group(1)
    asset_url = checksum_url = None
    for asset in item.get("assets", []):
        name = asset.get("name", "")
        if name == f"stats-collector-{version}.tar.gz":
            asset_url = asset.get("browser_download_url")
        elif name == f"stats-collector-{version}.tar.gz.sha256":
            checksum_url = asset.get("browser_download_url")
    return Release(
        version=version,
        tag=item["tag_name"],
        channel="test" if item.get("prerelease") else "production",
        name=item.get("name") or item["tag_name"],
        published_at=item.get("published_at"),
        url=item.get("html_url", ""),
        notes=split_languages(item.get("body") or ""),
        asset_url=asset_url,
        checksum_url=checksum_url,
    )


_cache: dict[str, tuple[float, list[Release]]] = {}
CACHE_SECONDS = 600


def fetch_releases(force: bool = False) -> list[Release]:
    settings = get_settings()
    key = settings.github_repo
    cached = _cache.get(key)
    if cached and not force and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "stats-collector-updater"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    resp = httpx.get(
        f"https://api.github.com/repos/{settings.github_repo}/releases",
        params={"per_page": 50},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    releases = [r for r in (release_from_github(i) for i in resp.json()) if r]
    releases.sort(key=lambda r: parse_version(r.version) or Version("0"), reverse=True)
    _cache[key] = (time.monotonic(), releases)
    return releases


def releases_for_channel(releases: list[Release], channel: str) -> list[Release]:
    """Production sees only production releases; test sees everything (newest first)."""
    if channel == "production":
        return [r for r in releases if r.channel == "production"]
    return list(releases)


def check(channel: str, releases: list[Release]) -> dict:
    current = build_info()
    current_v = parse_version(current["version"]) or Version("0")
    candidates = [r for r in releases_for_channel(releases, channel) if r.asset_url]
    latest = candidates[0] if candidates else None
    latest_v = parse_version(latest.version) if latest else None
    return {
        "current": current,
        "channel": channel,
        "latest": latest.to_dict() if latest else None,
        "update_available": bool(latest_v and latest_v > current_v),
        # Switching from test to production can mean going to a lower version number.
        "channel_mismatch": bool(
            latest_v and channel == "production" and current_v.is_prerelease and latest_v != current_v
        ),
    }
