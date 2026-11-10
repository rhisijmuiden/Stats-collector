"""Live wall service: serves /w/<token> and pushes the worker's snapshots to screens.

    uvicorn stats_collector.livewall.app:app --port 8081

It has no access to the database or the admin functions: it only reads the snapshots the worker
stores (see services/livewall.py). Screens get updates through Server-Sent Events; the page falls
back to fetching /w/<token>/data every 60 seconds. Requests are rate limited per IP address, and a
wall can be limited to a list of IP addresses or networks.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from ..config import get_settings
from ..proxy import ProxyHeadersMiddleware, _trusted, parse_networks
from ..services.livewall import store_get, token_hash

PAGE = (Path(__file__).parent / "wall.html").read_text(encoding="utf-8")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
RATE = 120  # requests per IP per minute
PUSH_EVERY = 15  # seconds between checks for a new snapshot
STREAM_SECONDS = 1800  # a screen reconnects after half an hour

HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' "
    "'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; "
    "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
}


class RateLimiter:
    def __init__(self, per_minute: int = RATE):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        q = self.hits[ip]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        if len(self.hits) > 10000:  # forget idle addresses
            for k in [k for k, v in self.hits.items() if not v][:5000]:
                del self.hits[k]
        return True


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title="Stats Collector live wall", docs_url=None, redoc_url=None, openapi_url=None)
    limiter = RateLimiter()

    def snapshot_for(request: Request, token: str) -> dict:
        ip = request.client.host if request.client else "?"
        if not limiter.allow(ip):
            raise HTTPException(429, "too_many_requests")
        if not TOKEN.match(token):
            raise HTTPException(404, "not_found")
        snap = store_get(token_hash(token))
        if snap is None:
            raise HTTPException(404, "not_found")
        allow = parse_networks(snap.get("allow_ips") or "")
        if allow and not _trusted(ip, allow):
            raise HTTPException(403, "forbidden")
        return snap

    def public(snap: dict) -> dict:
        return {k: v for k, v in snap.items() if k != "allow_ips"}

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/w/{token}", response_class=HTMLResponse)
    def page(token: str, request: Request) -> Response:
        snap = snapshot_for(request, token)
        html = PAGE.replace("__TITLE__", _escape(snap.get("title") or "Live")).replace(
            "__INITIAL__", json.dumps(public(snap)).replace("<", "\\u003c")
        )
        return HTMLResponse(html, headers=HEADERS)

    @app.get("/w/{token}/data")
    def data(token: str, request: Request) -> JSONResponse:
        return JSONResponse(public(snapshot_for(request, token)), headers=HEADERS)

    @app.get("/w/{token}/events")
    async def events(token: str, request: Request) -> StreamingResponse:
        snapshot_for(request, token)
        key = token_hash(token)

        async def stream():
            last = None
            started = time.monotonic()
            yield "retry: 15000\n\n"
            while time.monotonic() - started < STREAM_SECONDS:
                if await request.is_disconnected():
                    return
                snap = await asyncio.to_thread(store_get, key)
                if snap is None:  # revoked or switched off
                    yield "event: gone\ndata: {}\n\n"
                    return
                if snap.get("at") != last:
                    last = snap.get("at")
                    yield f"data: {json.dumps(public(snap))}\n\n"
                else:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(PUSH_EVERY)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={**HEADERS, "X-Accel-Buffering": "no"}
        )

    @app.exception_handler(HTTPException)
    async def errors(request: Request, exc: HTTPException):
        text = {
            404: "This wall does not exist or was switched off.",
            403: "Not allowed from this address.",
            429: "Too many requests, try again in a minute.",
        }.get(exc.status_code, "Error")
        if request.url.path.endswith(("/data", "/events")):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=HEADERS)
        return HTMLResponse(
            f'<!doctype html><meta charset="utf-8"><title>Live wall</title><body style="background:#060B16;'
            f'color:#D8F3FF;font:20px system-ui;display:grid;place-items:center;height:100vh;margin:0">{text}</body>',
            status_code=exc.status_code,
            headers=HEADERS,
        )

    return WallProxyHeaders(app, cfg.trusted_proxies, cfg.client_ip_header)


class WallProxyHeaders(ProxyHeadersMiddleware):
    """Trusted proxies from the config file plus the ones set under Live walls (read every minute).

    The wall service may sit behind its own reverse proxy on another machine; its address is set
    in the app, and the worker hands it over through the snapshot store."""

    def __init__(self, app, trusted: str, client_ip_header: str | None = None):
        super().__init__(app, trusted, client_ip_header)
        self.base = trusted
        self.loaded = 0.0

    async def __call__(self, scope, receive, send):
        if time.monotonic() - self.loaded > 60:
            self.loaded = time.monotonic()
            extra = (store_get("config") or {}).get("trusted_proxies") or ""
            self.nets = parse_networks(",".join(p for p in (self.base, extra) if p))
        await super().__call__(scope, receive, send)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


app = create_app()
