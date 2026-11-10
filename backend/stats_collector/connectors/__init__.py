"""Source connectors. Each one turns a remote API into samples for the collector.

A connector is stateless: it gets the source settings and secrets, talks to the remote
server and returns what it saw. Storing items and samples is done by services.collect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class ConnectorError(Exception):
    """A problem worth showing to the administrator (bad URL, wrong password, ...)."""


@dataclass
class Observation:
    """One item (mount, broadcast) at the moment of polling."""

    external_id: str
    kind: str
    title: str
    value: float
    online: bool = True
    url: str | None = None
    started_at: Any = None
    extra: dict = field(default_factory=dict)


@dataclass
class PollResult:
    online: bool
    observations: list[Observation]
    info: dict = field(default_factory=dict)  # e.g. server name and version, shown on the test button


class Connector(Protocol):
    kind: str
    stream: bool  # live audience source polled every few seconds

    def poll(self, config: dict, secrets: dict) -> PollResult: ...


def http_client(config: dict) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(10.0, connect=5.0),
        verify=bool(config.get("verify_tls", True)),
        follow_redirects=True,
        headers={"User-Agent": "StatsCollector/1"},
    )


def base_url(config: dict) -> str:
    url = str(config.get("url") or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ConnectorError("invalid_url")
    return url


def get_json(client: httpx.Client, url: str, **kwargs) -> Any:
    try:
        resp = client.get(url, **kwargs)
    except httpx.TimeoutException as exc:
        raise ConnectorError("timeout") from exc
    except httpx.HTTPError as exc:
        raise ConnectorError(f"connection_failed: {exc}") from exc
    if resp.status_code in (401, 403):
        raise ConnectorError("unauthorized")
    if resp.status_code == 404:
        raise ConnectorError("not_found")
    if resp.status_code >= 400:
        raise ConnectorError(f"http_{resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ConnectorError("invalid_response") from exc


def get_connector(kind: str) -> Connector:
    from . import icecast, owncast

    connectors = {"icecast": icecast.IcecastConnector(), "owncast": owncast.OwncastConnector()}
    if kind not in connectors:
        raise ConnectorError(f"unsupported_kind: {kind}")
    return connectors[kind]


STREAM_KINDS = ("icecast", "owncast")
