"""Admin → Sources: Icecast and Owncast servers, WordPress sites, YouTube, Facebook, Instagram, Bluesky, Mastodon."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import APP_ROOT
from ..config import get_settings
from ..connectors import ConnectorError
from ..connectors.icecast import normalise_mounts
from ..db import get_db
from ..models import ContentItem, Source, User
from ..security import encrypt_secret, new_token, require_admin
from ..services import collect, meta, social, threads, wordpress
from .common import audit

router = APIRouter(prefix="/api/sources", tags=["sources"])
hooks = APIRouter(prefix="/api/hooks", tags=["hooks"])

KINDS = ("icecast", "owncast", "wordpress", "youtube", "facebook", "instagram", "threads", "bluesky", "mastodon")
OAUTH_KINDS = ("youtube", "facebook", "instagram", "threads")
YT_KEEP = (
    "channel_id",
    "channel_title",
    "channel_url",
    "channel_started",
    "subscribers",
    "video_count",
    "history_until",
    "history_done",
    "channel_history_done",
    "last_full_list",
)
PLUGIN_DIR = APP_ROOT / "wordpress-plugin" / "stats-collector"


class SourceIn(BaseModel):
    kind: Literal[
        "icecast", "owncast", "wordpress", "youtube", "facebook", "instagram", "threads", "bluesky", "mastodon"
    ]
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=500)
    mounts: list[str] = Field(default_factory=list)
    admin_user: str = Field(default="admin", max_length=100)
    admin_password: str | None = None  # None = keep, "" = remove
    verify_tls: bool = True
    poll_seconds: int = Field(default=30, ge=10, le=3600)
    enabled: bool = True
    client_id: str = Field(default="", max_length=300)  # YouTube: Google OAuth client; Meta: App ID
    client_secret: str | None = Field(default=None, max_length=300)  # None = keep
    config_id: str = Field(default="", max_length=100)  # Meta: Facebook Login for Business configuration
    graph_version: str = Field(default="", max_length=10, pattern=r"^(v?\d{1,3}\.\d{1,2})?$")
    metric_overrides: dict[str, str] = Field(default_factory=dict)  # Meta: our metric -> Graph name
    account: str = Field(default="", max_length=300)  # Bluesky handle, Mastodon @name@server
    access_token: str | None = Field(default=None, max_length=500)  # Mastodon (optional); None = keep, "" = remove

    @model_validator(mode="after")
    def _check(self):
        self.url = self.url.strip().rstrip("/")
        if self.kind in OAUTH_KINDS:
            if not self.client_id.strip():
                raise ValueError("client_id_required")
            self.client_id = self.client_id.strip()
            self.url = ""
            self.metric_overrides = {
                k: v.strip()
                for k, v in self.metric_overrides.items()
                if k in meta.ALL_METRIC_KEYS and v.strip() and len(v) <= 80 and v.replace("_", "").strip().isalnum()
            }
        elif self.kind == "bluesky":
            self.account = social.clean_handle(self.account)
            if not self.account:
                raise ValueError("invalid_handle")
            self.url = ""
        elif self.kind == "mastodon":
            self.url, self.account = social.clean_account(self.account, self.url)
            if not self.account:
                raise ValueError("invalid_account")
            if not self.url.startswith("https://") or len(self.url) < 12:
                raise ValueError("invalid_url")
        elif not self.url.startswith(("http://", "https://")) or len(self.url) < 8:
            raise ValueError("invalid_url")
        return self


class TestIn(SourceIn):
    id: int | None = None


def _config(body: SourceIn, old: dict | None = None) -> dict:
    if body.kind == "youtube":
        keep = {k: v for k, v in (old or {}).items() if k in YT_KEEP}
        if (old or {}).get("client_id") not in (None, body.client_id):
            keep = {}  # another Google app: the old connection no longer applies
        return {**keep, "client_id": body.client_id}
    if body.kind in meta.KINDS:
        old = old or {}
        same_app = old.get("client_id") in (None, body.client_id)
        keep = {k: v for k, v in old.items() if k not in meta.SETTINGS} if same_app else {}
        if not same_app or old.get("graph_version", "") != body.graph_version:
            keep.pop("metric_names", None)
        return {
            **keep,
            "client_id": body.client_id,
            "config_id": body.config_id.strip(),
            "graph_version": body.graph_version.strip(),
            "metric_overrides": body.metric_overrides,
        }
    if body.kind in threads.KINDS:
        old = old or {}
        same_app = old.get("client_id") in (None, body.client_id)
        keep = {k: v for k, v in old.items() if k not in threads.SETTINGS} if same_app else {}
        return {**keep, "client_id": body.client_id}
    if body.kind in social.KINDS:
        old = old or {}
        same = old.get("account") == body.account and old.get("url", "") == body.url
        keep = {k: v for k, v in old.items() if k not in ("url", "account")} if same else {}
        return {**keep, "url": body.url, "account": body.account}
    if body.kind == "wordpress":
        keep = {
            k: v for k, v in (old or {}).items() if k in ("site_name", "plugin_version", "wp_version", "site_timezone")
        }
        return {**keep, "url": body.url}
    cfg = {"url": body.url, "verify_tls": body.verify_tls}
    if body.kind == "icecast":
        cfg["mounts"] = normalise_mounts(body.mounts)
        cfg["admin_user"] = body.admin_user or "admin"
    return cfg


def webhook_url(source: Source) -> str | None:
    if source.kind != "owncast" or not source.webhook_token:
        return None
    return f"{get_settings().public_url.rstrip('/')}/api/hooks/owncast/{source.webhook_token}"


def ingest_url() -> str:
    return f"{get_settings().public_url.rstrip('/')}/api/ingest/wordpress"


def youtube_out(s: Source, secrets: dict) -> dict:
    cfg = s.config or {}
    return {
        "client_id": cfg.get("client_id", ""),
        "client_secret_set": bool(secrets.get("client_secret")),
        "connected": bool(cfg.get("channel_id") and secrets.get("refresh_token")),
        "channel_title": cfg.get("channel_title"),
        "channel_url": cfg.get("channel_url"),
        "subscribers": cfg.get("subscribers"),
        "video_count": cfg.get("video_count"),
        "channel_started": cfg.get("channel_started"),
        "history_until": cfg.get("history_until"),
        "history_done": bool(cfg.get("history_done")),
        "redirect_uri": youtube_redirect_uri(),
    }


def meta_out(s: Source, secrets: dict) -> dict:
    cfg = s.config or {}
    return {
        "client_id": cfg.get("client_id", ""),
        "client_secret_set": bool(secrets.get("client_secret")),
        "config_id": cfg.get("config_id", ""),
        "graph_version": cfg.get("graph_version", ""),
        "graph_version_default": meta.GRAPH_VERSION,
        "metric_overrides": cfg.get("metric_overrides") or {},
        "metric_keys": [k for k in meta.ALL_METRIC_KEYS if k.startswith("fb_" if s.kind == "facebook" else "ig_")],
        "unsupported_metrics": cfg.get("unsupported_metrics") or [],
        "connected": bool(cfg.get("account_id") and secrets.get("page_token")),
        "choices": (cfg.get("choices") or []) if secrets.get("candidates") else [],
        "account_name": cfg.get("account_name"),
        "account_url": cfg.get("account_url"),
        "page_name": cfg.get("page_name"),
        "followers": cfg.get("followers"),
        "history_done": bool(cfg.get("history_done")),
        "redirect_uri": meta_redirect_uri(),
    }


def threads_out(s: Source, secrets: dict) -> dict:
    cfg = s.config or {}
    return {
        "client_id": cfg.get("client_id", ""),
        "client_secret_set": bool(secrets.get("client_secret")),
        "connected": bool(cfg.get("account_id") and secrets.get("token")),
        "account_name": cfg.get("account_name"),
        "account_url": cfg.get("account_url"),
        "followers": cfg.get("followers"),
        "history_done": bool(cfg.get("history_done")),
        "redirect_uri": threads_redirect_uri(),
    }


def threads_redirect_uri() -> str:
    return f"{get_settings().public_url.rstrip('/')}/api/connectors/threads/callback"


def social_out(s: Source, secrets: dict) -> dict:
    cfg = s.config or {}
    return {
        "account": cfg.get("account", ""),
        "access_token_set": bool(secrets.get("access_token")),
        "account_name": cfg.get("account_name"),
        "account_url": cfg.get("account_url"),
        "handle": cfg.get("handle"),
        "followers": cfg.get("followers"),
        "connected": bool(cfg.get("account_id")),
        "history_done": bool(cfg.get("posts_done")),
    }


def meta_redirect_uri() -> str:
    return f"{get_settings().public_url.rstrip('/')}/api/connectors/meta/callback"


def youtube_redirect_uri() -> str:
    return f"{get_settings().public_url.rstrip('/')}/api/connectors/youtube/callback"


def source_out(db: Session, s: Source, secret: str | None = None) -> dict:
    items = db.execute(select(func.count()).select_from(ContentItem).where(ContentItem.source_id == s.id)).scalar_one()
    secrets = collect.source_secrets(s)
    return {
        "id": s.id,
        "kind": s.kind,
        "name": s.name,
        "url": (s.config or {}).get("url"),
        "mounts": (s.config or {}).get("mounts", []),
        "admin_user": (s.config or {}).get("admin_user", "admin"),
        "admin_password_set": bool(secrets.get("admin_password")),
        "verify_tls": (s.config or {}).get("verify_tls", True),
        "poll_seconds": s.poll_seconds,
        "enabled": s.enabled,
        "webhook_url": webhook_url(s),
        "items": items,
        **(
            {
                "site_key": s.webhook_token,
                "ingest_url": ingest_url(),
                "site_name": (s.config or {}).get("site_name"),
                "plugin_version": (s.config or {}).get("plugin_version"),
                "secret": secret,  # only right after creating or renewing the key
            }
            if s.kind == "wordpress"
            else {}
        ),
        **(youtube_out(s, secrets) if s.kind == "youtube" else {}),
        **(meta_out(s, secrets) if s.kind in meta.KINDS else {}),
        **(social_out(s, secrets) if s.kind in social.KINDS else {}),
        **(threads_out(s, secrets) if s.kind in threads.KINDS else {}),
        "last_poll_at": s.last_poll_at.isoformat() if s.last_poll_at else None,
        "last_ok_at": s.last_ok_at.isoformat() if s.last_ok_at else None,
        "last_error": s.last_error,
        "last_error_at": s.last_error_at.isoformat() if s.last_error_at else None,
    }


def _apply(s: Source, body: SourceIn) -> None:
    s.kind = body.kind
    s.name = body.name.strip()
    s.config = _config(body, s.config)
    s.poll_seconds = body.poll_seconds
    s.enabled = body.enabled
    if s.kind in OAUTH_KINDS:
        secrets = collect.source_secrets(s)
        if s.kind == "youtube" and s.config.get("channel_id") is None:
            secrets.pop("refresh_token", None)
        if s.kind in threads.KINDS and s.config.get("account_id") is None:
            secrets.pop("token", None)
            secrets.pop("token_at", None)
        if s.kind in meta.KINDS and s.config.get("account_id") is None:
            secrets.pop("page_token", None)
            secrets.pop("candidates", None)
        if body.client_secret:
            secrets["client_secret"] = body.client_secret.strip()
        s.secret_enc = encrypt_secret(json.dumps(secrets)) if secrets else None
        s.poll_seconds = 3600
    if s.kind in social.KINDS:
        s.poll_seconds = 3600
        if body.access_token is not None:
            secrets = collect.source_secrets(s)
            if body.access_token.strip():
                secrets["access_token"] = body.access_token.strip()
            else:
                secrets.pop("access_token", None)
            s.secret_enc = encrypt_secret(json.dumps(secrets)) if secrets else None
    elif body.admin_password is not None and s.kind not in ("wordpress", *OAUTH_KINDS):
        secrets = collect.source_secrets(s)
        if body.admin_password:
            secrets["admin_password"] = body.admin_password
        else:
            secrets.pop("admin_password", None)
        s.secret_enc = encrypt_secret(json.dumps(secrets)) if secrets else None
    if s.kind == "owncast" and not s.webhook_token:
        s.webhook_token = new_token()


@router.get("")
def list_sources(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[dict]:
    rows = db.execute(select(Source).order_by(Source.kind, Source.name)).scalars()
    return [source_out(db, s) for s in rows]


@router.post("")
def create_source(body: SourceIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = Source(kind=body.kind, name=body.name)
    _apply(s, body)
    secret = wordpress.new_credentials(s) if s.kind == "wordpress" else None
    db.add(s)
    db.commit()
    audit(db, admin, "sources.create", {"id": s.id, "kind": s.kind, "name": s.name})
    if s.kind in social.KINDS and s.enabled:
        from ..worker import social_soon

        social_soon(s.id)
    return source_out(db, s, secret)


def _get(db: Session, source_id: int) -> Source:
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "not_found")
    return s


@router.put("/{source_id}")
def update_source(
    source_id: int, body: SourceIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    s = _get(db, source_id)
    if body.kind != s.kind:
        raise HTTPException(400, "kind_cannot_change")
    _apply(s, body)
    db.commit()
    audit(db, admin, "sources.update", {"id": s.id})
    return source_out(db, s)


@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = _get(db, source_id)
    db.delete(s)
    db.commit()
    audit(db, admin, "sources.delete", {"id": source_id, "name": s.name})
    return {"ok": True}


@router.post("/{source_id}/rotate-webhook")
def rotate_webhook(source_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = _get(db, source_id)
    if s.kind != "owncast":
        raise HTTPException(400, "no_webhook")
    s.webhook_token = new_token()
    db.commit()
    audit(db, admin, "sources.rotate_webhook", {"id": s.id})
    return source_out(db, s)


@router.post("/{source_id}/rotate-key")
def rotate_key(source_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = _get(db, source_id)
    if s.kind != "wordpress":
        raise HTTPException(400, "no_site_key")
    secret = wordpress.new_credentials(s)
    db.commit()
    audit(db, admin, "sources.rotate_key", {"id": s.id})
    return source_out(db, s, secret)


@router.get("/wordpress-plugin.zip")
def plugin_zip(_: User = Depends(require_admin)) -> Response:
    """The WordPress plugin bundled with this release, ready for Plugins → Add new → Upload."""
    if not PLUGIN_DIR.is_dir():
        raise HTTPException(404, "plugin_missing")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PLUGIN_DIR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, f"stats-collector/{path.relative_to(PLUGIN_DIR)}")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="stats-collector-wordpress.zip"'},
    )


@router.post("/test")
def test_source(body: TestIn, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    if body.kind == "wordpress":
        raise HTTPException(400, "test_in_wordpress")
    if body.kind in OAUTH_KINDS:
        raise HTTPException(
            400,
            {"youtube": "test_youtube_connect", "threads": "test_threads_connect"}.get(body.kind, "test_meta_connect"),
        )
    secrets: dict = {}
    if body.id is not None:
        secrets = collect.source_secrets(_get(db, body.id))
    if body.kind in social.KINDS:
        if body.access_token is not None:
            secrets = {"access_token": body.access_token.strip()} if body.access_token.strip() else {}
        try:
            account = social.lookup(body.kind, _config(body), secrets)
        except ConnectorError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "online": True,
            "info": {"server": account["handle"], "account": account["name"], "followers": account["followers"]},
            "items": [],
        }
    if body.admin_password is not None:
        secrets = {**secrets, "admin_password": body.admin_password} if body.admin_password else {}
    try:
        result = collect.test_source(body.kind, _config(body), secrets)
    except ConnectorError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "online": result.online,
        "info": result.info,
        "items": [
            {"id": o.external_id, "title": o.title, "value": o.value, "online": o.online} for o in result.observations
        ],
    }


@router.post("/{source_id}/poll")
def poll_now(source_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    s = _get(db, source_id)
    if s.kind == "wordpress":
        raise HTTPException(400, "push_only")
    if s.kind == "youtube":
        if not (s.config or {}).get("channel_id"):
            raise HTTPException(400, "yt_not_connected")
        from ..worker import youtube_soon

        youtube_soon(s.id)
        return source_out(db, s)
    if s.kind in meta.KINDS:
        if not (s.config or {}).get("account_id"):
            raise HTTPException(400, "meta_not_connected")
        from ..worker import meta_soon

        meta_soon(s.id)
        return source_out(db, s)
    if s.kind in social.KINDS:
        from ..worker import social_soon

        social_soon(s.id)
        return source_out(db, s)
    if s.kind in threads.KINDS:
        if not (s.config or {}).get("account_id"):
            raise HTTPException(400, "threads_not_connected")
        from ..worker import threads_soon

        threads_soon(s.id)
        return source_out(db, s)
    collect.poll_source(db, s)
    return source_out(db, s)


@hooks.post("/owncast/{token}")
async def owncast_webhook(
    token: str, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)
) -> dict:
    """Owncast → Integrations → Webhooks: "Stream started" and "Stream stopped" trigger a poll at once."""
    s = db.execute(select(Source).where(Source.kind == "owncast", Source.webhook_token == token)).scalar_one_or_none()
    if s is None or not s.enabled or len(token) < 20:
        raise HTTPException(404, "not_found")
    try:
        event = await request.json()
    except ValueError:
        event = {}
    kind = str((event or {}).get("type") or "")
    if kind in ("STREAM_STARTED", "STREAM_STOPPED", "STREAM_TITLE_UPDATED", ""):
        from ..worker import poll_soon

        background.add_task(poll_soon, s.id)
    return {"ok": True}
