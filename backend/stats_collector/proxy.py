"""Trusted reverse-proxy headers (replaces uvicorn's --proxy-headers).

Only when the direct peer is a trusted proxy (SC_TRUSTED_PROXIES: IPs or CIDR ranges):
- the client IP comes from SC_CLIENT_IP_HEADER when set (e.g. CF-Connecting-IP behind
  Cloudflare), otherwise from X-Forwarded-For, skipping trusted proxies from the right;
- the scheme comes from X-Forwarded-Proto.
"""

from __future__ import annotations

import ipaddress


def parse_networks(value: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets = []
    for part in (value or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            return [ipaddress.ip_network("0.0.0.0/0"), ipaddress.ip_network("::/0")]
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return nets


def _trusted(ip: str, nets) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def _valid_ip(value: str) -> str | None:
    value = value.strip().strip('"')
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


class ProxyHeadersMiddleware:
    def __init__(self, app, trusted: str = "127.0.0.1", client_ip_header: str | None = None):
        self.app = app
        self.nets = parse_networks(trusted)
        self.ip_header = client_ip_header.lower().encode() if client_ip_header else None

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope.get("client"):
            peer = scope["client"][0]
            if _trusted(peer, self.nets):
                headers = {}
                for k, v in scope.get("headers", []):
                    headers.setdefault(k, v.decode("latin-1"))
                client = None
                if self.ip_header and headers.get(self.ip_header):
                    client = _valid_ip(headers[self.ip_header])
                if client is None and headers.get(b"x-forwarded-for"):
                    for hop in reversed(headers[b"x-forwarded-for"].split(",")):
                        ip = _valid_ip(hop)
                        if ip is None:
                            break
                        client = ip
                        if not _trusted(ip, self.nets):
                            break
                proto = (headers.get(b"x-forwarded-proto") or "").split(",")[0].strip().lower()
                scope = dict(scope)
                if client:
                    scope["client"] = (client, 0)
                if proto in ("http", "https"):
                    scope["scheme"] = proto if scope["type"] == "http" else ("wss" if proto == "https" else "ws")
        await self.app(scope, receive, send)
