"""Icecast: listeners per mount from status-json.xsl, listening time from admin/listclients.

Some hosts remove status-json.xsl (and change status.xsl so it shows no mounts). With the admin user
and password the same numbers come from admin/stats, the XML page Icecast keeps for its admin
interface; that is used when status-json.xsl is missing.
"""

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


FIELDS = ("listeners", "listenurl", "server_name", "title", "stream_start_iso8601")


def parse_admin_stats(xml_text: str) -> dict:
    """admin/stats as the same shape as status-json.xsl: {"icestats": {"source": [...]}}."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ConnectorError("invalid_response") from exc
    if root.tag != "icestats":
        raise ConnectorError("invalid_response")
    sources = []
    for src in root.findall("source"):
        item: dict = {k: (src.findtext(k) or "").strip() or None for k in FIELDS}
        item["listeners"] = int(item["listeners"]) if (item["listeners"] or "").isdigit() else 0
        item["listenurl"] = item["listenurl"] or src.get("mount")
        sources.append(item)
    return {"icestats": {"server_id": (root.findtext("server_id") or "").strip() or None, "source": sources}}


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
        password = secrets.get("admin_password")
        user = config.get("admin_user") or "admin"
        with http_client(config) as client:
            try:
                data = get_json(client, f"{url}/status-json.xsl")
                via = "status-json"
            except ConnectorError as exc:
                if str(exc) not in ("not_found", "invalid_response"):
                    raise
                if not password:
                    raise ConnectorError("icecast_no_status") from exc
                data = parse_admin_stats(self._admin_get(client, f"{url}/admin/stats", user, password, required=True))
                via = "admin-stats"
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
        info = {"server": stats.get("server_id"), "mounts_found": sorted(seen), "via": via}
        return PollResult(online=any(o.online for o in observations), observations=observations, info=info)

    def _admin_get(
        self, client: httpx.Client, url: str, user: str, password: str, params=None, required: bool = False
    ) -> str | None:
        try:
            resp = client.get(url, params=params, auth=(user, password))
        except httpx.TimeoutException as exc:
            if required:
                raise ConnectorError("timeout") from exc
            return None
        except httpx.HTTPError as exc:
            if required:
                raise ConnectorError(f"connection_failed: {exc}") from exc
            return None
        if resp.status_code in (401, 403):
            raise ConnectorError("unauthorized")
        if resp.status_code != 200:
            if required:
                raise ConnectorError("not_found" if resp.status_code == 404 else f"http_{resp.status_code}")
            return None
        return resp.text

    def _listclients(self, client: httpx.Client, url: str, mount: str, user: str, password: str) -> dict:
        text = self._admin_get(client, f"{url}/admin/listclients", user, password, params={"mount": mount})
        return parse_listclients(text) if text else {}
