"""Live walls (admin): read-only screens for the newsroom, served by the wall service on port 8081.

GET    /api/livewalls                  admin: walls with their link
POST   /api/livewalls                  admin: a new wall with a fresh, unguessable link
PUT    /api/livewalls/{id}             admin: name, title, channels, allowed IPs, on/off
POST   /api/livewalls/{id}/rotate      admin: a new link; the old one stops working within a minute
DELETE /api/livewalls/{id}             admin
GET    /api/livewalls/{id}/preview     admin: the snapshot the wall shows now
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import LiveWall, Source, User, utcnow
from ..proxy import parse_networks
from ..security import decrypt_secret, encrypt_secret, require_role
from ..services import livewall as svc
from ..services import settings_store
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
        "url": f"{base}/w/{token}",
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "rotated_at": w.rotated_at.isoformat() if w.rotated_at else None,
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
