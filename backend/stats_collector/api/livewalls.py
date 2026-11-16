"""Live walls (admin): read-only screens for the newsroom, served by the wall service on port 8081.

GET    /api/livewalls                  admin: walls with their link
POST   /api/livewalls                  admin: a new wall with a fresh, unguessable link
PUT    /api/livewalls/{id}             admin: name, title, channels, layout, allowed IPs, on/off
POST   /api/livewalls/{id}/rotate      admin: a new link; the old one stops working within a minute
DELETE /api/livewalls/{id}             admin
GET    /api/livewalls/{id}/preview     admin: the snapshot the wall shows now

Wall Designer (see services/walldesign.py):
GET    /api/livewalls/{id}/design              admin: published design, draft, versions and templates
PUT    /api/livewalls/{id}/design/draft        admin: save the editor's work without touching the TVs
DELETE /api/livewalls/{id}/design/draft        admin: throw the draft away
POST   /api/livewalls/{id}/design/publish      admin: put a design on the TVs (a new version)
POST   /api/livewalls/{id}/design/standard     admin: back to the standard screens (also a new version)
GET    /api/livewalls/designer-frame           admin: the wall page for the editor's live preview
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import LiveWall, LiveWallVersion, Source, User, utcnow
from ..proxy import parse_networks
from ..security import decrypt_secret, encrypt_secret, require_role
from ..services import livewall as svc
from ..services import settings_store, walldesign
from .common import audit
from .settings import effective_theme

router = APIRouter(prefix="/api/livewalls", tags=["livewalls"])
admin_only = require_role("admin")


class WallIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    source_ids: list[int] = Field(default_factory=list, max_length=50)
    allow_ips: str = Field(default="", max_length=1000)
    enabled: bool = True
    layout: Literal["rotate", "overview", "stories"] = "rotate"
    rotate_seconds: int = Field(default=30, ge=10, le=300)
    show_authors: bool = True

    @field_validator("allow_ips")
    @classmethod
    def _ips(cls, v: str) -> str:
        parts = [p.strip() for p in v.replace(";", ",").replace("\n", ",").split(",") if p.strip()]
        for p in parts:
            if p == "*" or not parse_networks(p):
                raise ValueError("invalid_ip")
        return ", ".join(parts)


class WallConfigIn(BaseModel):
    public_url: str = Field(default="", max_length=300)
    trusted_proxies: str = Field(default="", max_length=1000)

    @field_validator("public_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and (not v.startswith(("http://", "https://")) or len(v) < 10 or "?" in v or "#" in v or " " in v):
            raise ValueError("invalid_url")
        return v

    @field_validator("trusted_proxies")
    @classmethod
    def _proxies(cls, v: str) -> str:
        parts = [p.strip() for p in v.replace(";", ",").replace("\n", ",").split(",") if p.strip()]
        for p in parts:
            if p == "*" or not parse_networks(p):
                raise ValueError("invalid_ip")
        return ", ".join(parts)


def _out(w: LiveWall, base: str) -> dict:
    token = decrypt_secret(w.token_enc) or ""
    return {
        "id": w.id,
        "name": w.name,
        "title": w.title,
        "source_ids": w.source_ids or [],
        "allow_ips": w.allow_ips,
        "enabled": w.enabled,
        "layout": w.layout or "rotate",
        "rotate_seconds": w.rotate_seconds or 30,
        "show_authors": bool(w.show_authors),
        "url": f"{base}/w/{token}",
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "rotated_at": w.rotated_at.isoformat() if w.rotated_at else None,
        "custom_design": w.design is not None,
        "design_version": w.design_version or 0,
        "has_draft": w.design_draft is not None,
    }


def _check_sources(db: Session, ids: list[int]) -> None:
    found = set(db.execute(select(Source.id).where(Source.id.in_(ids), Source.kind.in_(svc.WALL_KINDS))).scalars())
    if ids and found != set(ids):
        raise HTTPException(400, "unknown_source")


def _refresh() -> None:
    from ..worker import livewall_soon

    livewall_soon()


@router.get("/config")
def get_config(db: Session = Depends(get_db), _: User = Depends(admin_only)) -> dict:
    cfg = settings_store.get_section(db, "livewall")
    return {
        "public_url": cfg.get("public_url") or "",
        "trusted_proxies": cfg.get("trusted_proxies") or "",
        "default_url": get_settings().wall_base_url,
    }


@router.put("/config")
def put_config(body: WallConfigIn, db: Session = Depends(get_db), user: User = Depends(admin_only)) -> dict:
    settings_store.update_section(db, "livewall", body.model_dump())
    audit(db, user, "livewalls.config", body.model_dump())
    _refresh()
    return get_config(db, user)


@router.get("")
def list_walls(db: Session = Depends(get_db), _: User = Depends(admin_only)) -> dict:
    walls = db.execute(select(LiveWall).order_by(LiveWall.name)).scalars()
    base = svc.base_url(db)
    sources = db.execute(select(Source).where(Source.kind.in_(svc.WALL_KINDS)).order_by(Source.kind, Source.name))
    return {
        "walls": [_out(w, base) for w in walls],
        "sources": [{"id": s.id, "name": s.name, "kind": s.kind} for s in sources.scalars()],
        "base_url": base,
    }


@router.post("")
def create_wall(body: WallIn, db: Session = Depends(get_db), user: User = Depends(admin_only)) -> dict:
    _check_sources(db, body.source_ids)
    token = svc.new_token()
    w = LiveWall(
        **body.model_dump(), token_enc=encrypt_secret(token), token_hash=svc.token_hash(token), created_by=user.id
    )
    db.add(w)
    db.commit()
    audit(db, user, "livewalls.create", {"id": w.id, "name": w.name})
    _refresh()
    return _out(w, svc.base_url(db))


def _get(db: Session, wall_id: int) -> LiveWall:
    w = db.get(LiveWall, wall_id)
    if w is None:
        raise HTTPException(404, "not_found")
    return w


@router.put("/{wall_id}")
def update_wall(wall_id: int, body: WallIn, db: Session = Depends(get_db), user: User = Depends(admin_only)) -> dict:
    w = _get(db, wall_id)
    _check_sources(db, body.source_ids)
    for k, v in body.model_dump().items():
        setattr(w, k, v)
    db.commit()
    audit(db, user, "livewalls.update", {"id": w.id})
    _refresh()
    return _out(w, svc.base_url(db))


@router.post("/{wall_id}/rotate")
def rotate_wall(wall_id: int, db: Session = Depends(get_db), user: User = Depends(admin_only)) -> dict:
    w = _get(db, wall_id)
    svc.store_delete(w.token_hash)  # the old link stops at once
    token = svc.new_token()
    w.token_enc, w.token_hash, w.rotated_at = encrypt_secret(token), svc.token_hash(token), utcnow()
    db.commit()
    audit(db, user, "livewalls.rotate", {"id": w.id})
    _refresh()
    return _out(w, svc.base_url(db))


@router.delete("/{wall_id}")
def delete_wall(wall_id: int, db: Session = Depends(get_db), user: User = Depends(admin_only)) -> dict:
    w = _get(db, wall_id)
    svc.store_delete(w.token_hash)
    db.delete(w)
    db.commit()
    audit(db, user, "livewalls.delete", {"id": wall_id})
    return {"ok": True}


@router.get("/{wall_id}/preview")
def preview(wall_id: int, db: Session = Depends(get_db), _: User = Depends(admin_only)) -> dict:
    return svc.snapshot(db, _get(db, wall_id), effective_theme(db))


# ----------------------------------------------------------------------------- Wall Designer

FRAME_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' "
    "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src data:; frame-ancestors 'self'; "
    "base-uri 'none'",
}


@router.get("/designer-frame", response_class=HTMLResponse, include_in_schema=False)
def designer_frame(_: User = Depends(admin_only)) -> HTMLResponse:
    """The wall page without data: the editor hands it the snapshot and the design it is working on."""
    from ..livewall.app import PAGE

    html = PAGE.replace("__TITLE__", "Preview").replace("__INITIAL__", "null")
    return HTMLResponse(html, headers=FRAME_HEADERS)


def _validated(db: Session, body: walldesign.Design) -> dict:
    ids = {i for screen in body.screens for b in screen.blocks for i in b.channels}
    if ids:
        _check_sources(db, sorted(ids))
    return body.model_dump()


def _design_out(db: Session, w: LiveWall) -> dict:
    rows = db.execute(
        select(LiveWallVersion, User.display_name)
        .outerjoin(User, User.id == LiveWallVersion.created_by)
        .where(LiveWallVersion.wall_id == w.id)
        .order_by(LiveWallVersion.version.desc())
    ).all()
    return {
        "design": walldesign.effective(w),
        "custom": w.design is not None,
        "draft": w.design_draft,
        "version": w.design_version or 0,
        "versions": [
            {
                "version": v.version,
                "design": v.design,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "created_by": name or "",
            }
            for v, name in rows
        ],
        "templates": walldesign.templates(),
        "grid": {"cols": walldesign.COLS, "rows": walldesign.ROWS},
    }


@router.get("/{wall_id}/design")
def get_design(wall_id: int, db: Session = Depends(get_db), _: User = Depends(admin_only)) -> dict:
    return _design_out(db, _get(db, wall_id))


@router.put("/{wall_id}/design/draft")
def save_draft(
    wall_id: int, body: walldesign.Design, db: Session = Depends(get_db), user: User = Depends(admin_only)
) -> dict:
    w = _get(db, wall_id)
    w.design_draft = _validated(db, body)
    db.commit()
    return {"ok": True}


@router.delete("/{wall_id}/design/draft")
def drop_draft(wall_id: int, db: Session = Depends(get_db), _: User = Depends(admin_only)) -> dict:
    w = _get(db, wall_id)
    w.design_draft = None
    db.commit()
    return _design_out(db, w)


def _new_version(db: Session, w: LiveWall, design: dict | None, user: User) -> None:
    w.design = design
    w.design_draft = None
    w.design_version = (w.design_version or 0) + 1
    db.add(
        LiveWallVersion(
            wall_id=w.id, version=w.design_version, design=design or walldesign.effective(w), created_by=user.id
        )
    )
    db.commit()
    old = db.execute(
        select(LiveWallVersion)
        .where(LiveWallVersion.wall_id == w.id)
        .order_by(LiveWallVersion.version.desc())
        .offset(walldesign.MAX_VERSIONS)
    ).scalars()
    for v in old:
        db.delete(v)
    db.commit()


@router.post("/{wall_id}/design/publish")
def publish_design(
    wall_id: int, body: walldesign.Design, db: Session = Depends(get_db), user: User = Depends(admin_only)
) -> dict:
    w = _get(db, wall_id)
    _new_version(db, w, _validated(db, body), user)
    audit(db, user, "livewalls.design", {"id": w.id, "version": w.design_version})
    _refresh()
    return _design_out(db, w)


@router.post("/{wall_id}/design/standard")
def standard_design(wall_id: int, db: Session = Depends(get_db), user: User = Depends(admin_only)) -> dict:
    w = _get(db, wall_id)
    _new_version(db, w, None, user)
    audit(db, user, "livewalls.design", {"id": w.id, "version": w.design_version, "standard": True})
    _refresh()
    return _design_out(db, w)
