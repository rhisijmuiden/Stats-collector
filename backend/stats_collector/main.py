from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_ROOT, build_info
from .api import (
    auth,
    backup,
    content,
    dashboard,
    dashboards,
    entra,
    goals,
    help,
    ingest,
    meta,
    settings,
    sources,
    system,
    users,
    youtube,
)
from .config import get_settings
from .proxy import ProxyHeadersMiddleware


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title="Stats Collector",
        version=build_info()["version"],
        docs_url=None if cfg.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if cfg.is_production else "/api/openapi.json",
    )

    app.add_middleware(ProxyHeadersMiddleware, trusted=cfg.trusted_proxies, client_ip_header=cfg.client_ip_header)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": "validation_error",
                "errors": [{k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in exc.errors()],
            },
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'",
        )
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/api/health")
    def health() -> dict:
        info = build_info()
        return {"status": "ok", "version": info["version"]}

    for module in (
        auth,
        entra,
        users,
        settings,
        system,
        backup,
        help,
        sources,
        dashboard,
        content,
        ingest,
        youtube,
        meta,
        goals,
        dashboards,
    ):
        app.include_router(module.router)
    app.include_router(settings.public_router)
    app.include_router(sources.hooks)

    images = APP_ROOT / "docs" / "manual" / "images"
    if images.is_dir():
        app.mount("/help-assets", StaticFiles(directory=images), name="help-assets")

    static = cfg.static_dir or (APP_ROOT / "frontend" / "dist")
    if static.is_dir():
        assets = static / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")
        index = static / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "not_found"})
            candidate = (static / path).resolve()
            if path and candidate.is_file() and Path(static.resolve()) in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
