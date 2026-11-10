"""Owncast: live viewers from /api/status (or the admin API when a password is set)."""

from __future__ import annotations

from . import ConnectorError, Observation, PollResult, base_url, get_json, http_client


class OwncastConnector:
    kind = "owncast"
    stream = True

    def poll(self, config: dict, secrets: dict) -> PollResult:
        url = base_url(config)
        password = secrets.get("admin_password")
        with http_client(config) as client:
            if password:
                status = get_json(client, f"{url}/api/admin/status", auth=("admin", password))
            else:
                status = get_json(client, f"{url}/api/status")
            if not isinstance(status, dict) or "online" not in status:
                raise ConnectorError("invalid_response")
            try:
                server = get_json(client, f"{url}/api/config")
            except ConnectorError:
                server = {}
        online = bool(status.get("online"))
        name = (server or {}).get("name") or "Owncast"
        info = {"server": name, "version": status.get("versionNumber") or (server or {}).get("version")}
        if not online:
            return PollResult(online=False, observations=[], info=info)
        broadcaster = status.get("broadcaster") or {}
        started = status.get("lastConnectTime") or broadcaster.get("time")
        if not started:
            raise ConnectorError("invalid_response")
        title = status.get("streamTitle") or (server or {}).get("streamTitle") or name
        extra = {}
        for key in ("sessionPeakViewerCount", "overallPeakViewerCount"):
            if status.get(key) is not None:
                extra[key] = status[key]
        obs = Observation(
            external_id=f"broadcast:{started}",
            kind="broadcast",
            title=str(title)[:500],
            value=float(status.get("viewerCount") or 0),
            url=url,
            started_at=started,
            extra=extra,
        )
        return PollResult(online=True, observations=[obs], info=info)
