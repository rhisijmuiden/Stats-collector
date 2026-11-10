"""Icecast: listeners per mount from status-json.xsl, listening time from admin/listclients."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import urlparse

import httpx

from . import ConnectorError, Observation, PollResult, base_url, get_json, http_client


def _mount_of(src: dict) -> str:
    url = src.get("listenurl") or ""
    path = urlparse(url).path if "://" in url else url
    return path or "/"


def normalise_mounts(value) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\s,]+", value)
    mounts = []
    for m in value or []:
        m = str(m).strip()
        if m:
            mounts.append(m if m.startswith("/") else "/" + m)
    return mounts


def _agent_family(agent: str) -> str:
    a = agent.lower()
    for key, name in (
        ("vlc", "VLC"),
        ("itunes", "iTunes"),
        ("winamp", "Winamp"),
        ("foobar", "foobar2000"),
        ("sonos", "Sonos"),
        ("alexa", "Alexa"),
        ("android", "Android"),
        ("iphone", "iOS"),
        ("ipad", "iOS"),
        ("firefox", "Firefox"),
        ("edg/", "Edge"),
        ("chrome", "Chrome"),
        ("safari", "Safari"),
        ("mpv", "mpv"),
        ("lavf", "ffmpeg"),
    ):
        if key in a:
            return name
    return "Other"


def parse_listclients(xml_text: str) -> dict:
    """Average connected time and player families; IP addresses are never kept."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ConnectorError("invalid_response") from exc
    durations: list[int] = []
    agents: Counter[str] = Counter()
    for listener in root.iter("listener"):
        connected = listener.findtext("Connected") or listener.findtext("connected")
        if connected and connected.strip().isdigit():
            durations.append(int(connected.strip()))
        agents[_agent_family(listener.findtext("UserAgent") or listener.findtext("useragent") or "")] += 1
    out: dict = {"agents": dict(agents.most_common(8))}
    if durations:
        out["avg_connected_s"] = round(sum(durations) / len(durations))
    return out


class IcecastConnector:
    kind = "icecast"
    stream = True

    def poll(self, config: dict, secrets: dict) -> PollResult:
        url = base_url(config)
        wanted = normalise_mounts(config.get("mounts"))
        with http_client(config) as client:
            data = get_json(client, f"{url}/status-json.xsl")
            stats = (data or {}).get("icestats")
            if not isinstance(stats, dict):
                raise ConnectorError("invalid_response")
            sources = stats.get("source") or []
            if isinstance(sources, dict):
                sources = [sources]
            seen: dict[str, dict] = {}
            for src in sources:
                if isinstance(src, dict):
                    seen[_mount_of(src)] = src

            mounts = wanted or sorted(seen)
            password = secrets.get("admin_password")
            user = config.get("admin_user") or "admin"
            observations = []
            for mount in mounts:
                src = seen.get(mount)
                if src is None:
                    observations.append(
                        Observation(external_id=mount, kind="mount", title=mount, value=0, online=False)
                    )
                    continue
                extra: dict = {}
                if src.get("title"):
                    extra["now_playing"] = str(src.get("title"))[:300]
                if password and src.get("listeners"):
                    extra.update(self._listclients(client, url, mount, user, password))
                observations.append(
                    Observation(
                        external_id=mount,
                        kind="mount",
                        title=str(src.get("server_name") or mount)[:500],
                        value=float(src.get("listeners") or 0),
                        url=src.get("listenurl"),
                        started_at=src.get("stream_start_iso8601"),
                        extra=extra,
                    )
                )
        info = {"server": stats.get("server_id"), "mounts_found": sorted(seen)}
        return PollResult(online=any(o.online for o in observations), observations=observations, info=info)

    def _listclients(self, client: httpx.Client, url: str, mount: str, user: str, password: str) -> dict:
        try:
            resp = client.get(f"{url}/admin/listclients", params={"mount": mount}, auth=(user, password))
        except httpx.HTTPError:
            return {}
        if resp.status_code in (401, 403):
            raise ConnectorError("unauthorized")
        if resp.status_code != 200:
            return {}
        return parse_listclients(resp.text)
