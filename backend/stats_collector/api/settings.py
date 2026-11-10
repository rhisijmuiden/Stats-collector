from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .. import APP_ROOT
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..security import current_user, encrypt_secret, require_admin
from ..services import entra, mail, settings_store
from .common import audit

router = APIRouter(prefix="/api/settings", tags=["settings"])
public_router = APIRouter(prefix="/api/branding", tags=["branding"])

DEFAULT_THEME = APP_ROOT / "branding" / "default" / "theme.json"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _keep_or_set(current: dict, field: str, value: str | None) -> None:
    """None keeps the stored secret, empty string clears it, anything else replaces it."""
    if value is None:
        return
    current[field] = encrypt_secret(value) if value else None


# --- general ---------------------------------------------------------------------------------------------


class GeneralIn(BaseModel):
    organization: str = Field(min_length=1, max_length=200)
    default_language: Literal["en", "nl"] = "en"
    timezone: str = "Europe/Amsterdam"


@router.get("/general")
def get_general(db: Session = Depends(get_db), _=Depends(current_user)) -> dict:
    return settings_store.get_section(db, "general")


@router.put("/general")
def put_general(body: GeneralIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(400, "invalid_timezone") from exc
    value = settings_store.update_section(db, "general", body.model_dump())
    audit(db, admin, "settings.general")
    return value


# --- email -----------------------------------------------------------------------------------------------


class EmailIn(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = Field(587, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    auth: Literal["password", "xoauth2", "none"] = "password"
    username: str = ""
    password: str | None = None
    oauth_token_url: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str | None = None
    oauth_scope: str = ""
    from_address: str = ""
    from_name: str = ""
    reply_to: str = ""
    verify_tls: bool = True
    timeout: int = Field(20, ge=3, le=120)
    transport: Literal["smtp", "graph"] = "smtp"
    graph_tenant_id: str = Field("", max_length=100)
    graph_client_id: str = Field("", max_length=100)
    graph_client_secret: str | None = None
    graph_mailbox: str = Field("", max_length=320)


class EmailTestIn(BaseModel):
    to: EmailStr


@router.get("/email")
def get_email(db: Session = Depends(get_db), _=Depends(require_admin)) -> dict:
    return settings_store.public_view("email", settings_store.get_section(db, "email"))


@router.put("/email")
def put_email(body: EmailIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    current = settings_store.get_section(db, "email")
    data = body.model_dump(exclude={"password", "oauth_client_secret", "graph_client_secret"})
    current.update(data)
    _keep_or_set(current, "password_enc", body.password)
    _keep_or_set(current, "oauth_client_secret_enc", body.oauth_client_secret)
    _keep_or_set(current, "graph_client_secret_enc", body.graph_client_secret)
    settings_store.set_section(db, "email", current)
    audit(db, admin, "settings.email")
    return settings_store.public_view("email", current)


@router.post("/email/test")
def test_email(body: EmailTestIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    cfg = settings_store.get_section(db, "email")
    try:
        mail.send(cfg, mail.test_mail(body.to, admin.language))
    except mail.MailError as exc:
        raise HTTPException(502, f"mail_failed: {exc}") from exc
    audit(db, admin, "settings.email_test", {"to": body.to})
    return {"ok": True}


# --- single sign-on (Entra ID) groundwork ---------------------------------------------------------------


class SsoIn(BaseModel):
    enabled: bool = False
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str | None = None
    allow_local_login: bool = True
    group_roles: dict[str, str] = Field(default_factory=dict)
    default_role: Literal["admin", "editor_in_chief", "editor", "staff"] = "staff"


@router.get("/sso")
def get_sso(db: Session = Depends(get_db), _=Depends(require_admin)) -> dict:
    value = settings_store.public_view("sso", settings_store.get_section(db, "sso"))
    value["redirect_uri"] = get_settings().public_url.rstrip("/") + "/api/auth/entra/callback"
    value["app_roles"] = entra.app_roles()
    return value


@router.put("/sso")
def put_sso(body: SsoIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    current = settings_store.get_section(db, "sso")
    data = body.model_dump(exclude={"client_secret"})
    data["group_roles"] = {k: v.strip() for k, v in data["group_roles"].items() if k in current["group_roles"]}
    current.update(data)
    _keep_or_set(current, "client_secret_enc", body.client_secret)
    settings_store.set_section(db, "sso", current)
    audit(db, admin, "settings.sso")
    return settings_store.public_view("sso", current)


# --- backup schedule -------------------------------------------------------------------------------------


class BackupSettingsIn(BaseModel):
    schedule_enabled: bool = False
    full_every: Literal["daily", "weekly", "monthly"] = "weekly"
    full_weekday: int = Field(6, ge=0, le=6)
    incremental_every_hours: int = Field(24, ge=1, le=168)
    time: str = Field("02:30", pattern=r"^\d{2}:\d{2}$")
    retention_full: int = Field(4, ge=1, le=52)
    include_uploads: bool = True
    encryption_passphrase: str | None = None


@router.get("/backup")
def get_backup_settings(db: Session = Depends(get_db), _=Depends(require_admin)) -> dict:
    return settings_store.public_view("backup", settings_store.get_section(db, "backup"))


@router.put("/backup")
def put_backup_settings(
    body: BackupSettingsIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    current = settings_store.get_section(db, "backup")
    current.update(body.model_dump(exclude={"encryption_passphrase"}))
    if body.encryption_passphrase is not None and body.encryption_passphrase and len(body.encryption_passphrase) < 12:
        raise HTTPException(400, "passphrase_too_short")
    _keep_or_set(current, "encryption_passphrase_enc", body.encryption_passphrase)
    settings_store.set_section(db, "backup", current)
    audit(db, admin, "settings.backup")
    return settings_store.public_view("backup", current)


# --- branding --------------------------------------------------------------------------------------------


def default_theme() -> dict:
    return json.loads(DEFAULT_THEME.read_text())


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def effective_theme(db: Session) -> dict:
    cfg = settings_store.get_section(db, "branding")
    theme = _deep_merge(default_theme(), cfg.get("overrides") or {})
    theme["app_name"] = cfg.get("app_name") or "Stats Collector"
    for kind in ("logo_light", "logo_dark", "favicon"):
        theme.setdefault("assets", {})[kind] = f"/api/branding/asset/{kind}" if cfg.get(kind) else None
    return theme


def _validate_colors(node, path="") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _validate_colors(v, f"{path}.{k}")
    elif isinstance(node, str) and ("color" in path or "channels" in path or "liveWall" in path):
        if not HEX.match(node):
            raise HTTPException(400, f"invalid_color{path}")


class BrandingIn(BaseModel):
    app_name: str = Field("Stats Collector", min_length=1, max_length=80)
    overrides: dict = Field(default_factory=dict)


@public_router.get("")
def get_branding(db: Session = Depends(get_db)) -> dict:
    return effective_theme(db)


@public_router.get("/asset/{kind}")
def branding_asset(kind: Literal["logo_light", "logo_dark", "favicon"], db: Session = Depends(get_db)):
    name = settings_store.get_section(db, "branding").get(kind)
    if not name:
        raise HTTPException(404, "not_found")
    path = get_settings().uploads_dir / "branding" / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "not_found")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=300"})


@router.get("/branding")
def get_branding_settings(db: Session = Depends(get_db), _=Depends(require_admin)) -> dict:
    cfg = settings_store.get_section(db, "branding")
    return {
        "app_name": cfg.get("app_name"),
        "overrides": cfg.get("overrides") or {},
        "default": default_theme(),
        "effective": effective_theme(db),
    }


@router.put("/branding")
def put_branding(body: BrandingIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    allowed = {"colors", "channels", "fonts", "radius", "liveWall"}
    overrides = {k: v for k, v in body.overrides.items() if k in allowed}
    _validate_colors(overrides)
    settings_store.update_section(db, "branding", {"app_name": body.app_name, "overrides": overrides})
    audit(db, admin, "settings.branding")
    return effective_theme(db)


MAX_LOGO = 2 * 1024 * 1024
LOGO_TYPES = {"image/svg+xml": ".svg", "image/png": ".png", "image/webp": ".webp", "image/x-icon": ".ico"}


@router.post("/branding/{kind}")
async def upload_logo(
    kind: Literal["logo_light", "logo_dark", "favicon"],
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    ext = LOGO_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "unsupported_file_type")
    data = await file.read(MAX_LOGO + 1)
    if len(data) > MAX_LOGO:
        raise HTTPException(400, "file_too_large")
    if ext == ".svg" and (b"<script" in data.lower() or b"javascript:" in data.lower()):
        raise HTTPException(400, "unsafe_svg")
    folder = get_settings().uploads_dir / "branding"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{kind}{ext}"
    for old in folder.glob(f"{kind}.*"):
        old.unlink()
    (folder / name).write_bytes(data)
    settings_store.update_section(db, "branding", {kind: name})
    audit(db, admin, "settings.branding_asset", {"kind": kind})
    return effective_theme(db)


@router.delete("/branding/{kind}")
def delete_logo(
    kind: Literal["logo_light", "logo_dark", "favicon"],
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    settings_store.update_section(db, "branding", {kind: None})
    audit(db, admin, "settings.branding_asset_removed", {"kind": kind})
    return effective_theme(db)
