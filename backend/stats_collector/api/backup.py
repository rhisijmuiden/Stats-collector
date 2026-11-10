from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BackupRecord, BackupTarget, User
from ..security import encrypt_secret, require_admin
from ..services import ops
from .common import audit
from .system import _busy, job_out

router = APIRouter(prefix="/api/backup", tags=["backup"])

HOST_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:[]")


class TargetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["ftp", "ftps", "sftp"]
    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    secret: str | None = None  # password or private key; None keeps the stored one
    auth_method: Literal["password", "key"] = "password"
    path: str = Field("stats-collector", max_length=500)
    ftps_mode: Literal["explicit", "implicit"] = "explicit"
    verify_tls: bool = True
    enabled: bool = True

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        v = v.strip()
        if not set(v) <= HOST_CHARS:
            raise ValueError("invalid_host")
        return v

    @field_validator("path", "username")
    @classmethod
    def _no_newlines(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("invalid_value")
        return v.strip()


def target_out(t: BackupTarget) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "kind": t.kind,
        "host": t.host,
        "port": t.port,
        "username": t.username,
        "auth_method": t.auth_method,
        "secret_set": bool(t.secret_enc),
        "path": t.path,
        "ftps_mode": t.ftps_mode,
        "verify_tls": t.verify_tls,
        "enabled": t.enabled,
    }


@router.get("/targets")
def list_targets(db: Session = Depends(get_db), _=Depends(require_admin)) -> list[dict]:
    return [target_out(t) for t in db.execute(select(BackupTarget).order_by(BackupTarget.name)).scalars()]


@router.post("/targets", status_code=201)
def create_target(body: TargetIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    t = BackupTarget(**body.model_dump(exclude={"secret"}), secret_enc=encrypt_secret(body.secret))
    db.add(t)
    db.commit()
    audit(db, admin, "backup.target_created", {"id": t.id, "kind": t.kind})
    return target_out(t)


@router.put("/targets/{target_id}")
def update_target(
    target_id: int, body: TargetIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    t = db.get(BackupTarget, target_id)
    if t is None:
        raise HTTPException(404, "not_found")
    for k, v in body.model_dump(exclude={"secret"}).items():
        setattr(t, k, v)
    if body.secret is not None:
        t.secret_enc = encrypt_secret(body.secret)
    db.commit()
    audit(db, admin, "backup.target_updated", {"id": t.id})
    return target_out(t)


@router.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    t = db.get(BackupTarget, target_id)
    if t is None:
        raise HTTPException(404, "not_found")
    db.delete(t)
    db.commit()
    audit(db, admin, "backup.target_deleted", {"id": target_id})
    return {"ok": True}


def _enqueue(db: Session, kind: str, params: dict, admin: User) -> dict:
    if _busy(db):
        raise HTTPException(409, "job_running")
    try:
        job = ops.enqueue(db, kind, params, admin)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, admin, f"backup.{kind}", params)
    return job_out(job)


@router.post("/targets/{target_id}/test", status_code=202)
def test_target(target_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    if db.get(BackupTarget, target_id) is None:
        raise HTTPException(404, "not_found")
    return _enqueue(db, "verify_target", {"target_id": target_id}, admin)


class RunIn(BaseModel):
    type: Literal["full", "incr"]


@router.post("/run", status_code=202)
def run_backup(body: RunIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return _enqueue(db, "backup", {"type": body.type}, admin)


class RestoreIn(BaseModel):
    target_id: int
    label: str
    confirm: str


@router.post("/restore", status_code=202)
def restore(body: RestoreIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    if body.confirm != "RESTORE":
        raise HTTPException(400, "confirmation_required")
    if db.get(BackupTarget, body.target_id) is None:
        raise HTTPException(404, "not_found")
    return _enqueue(db, "restore", {"target_id": body.target_id, "label": body.label}, admin)


@router.get("/records")
def records(db: Session = Depends(get_db), _=Depends(require_admin)) -> list[dict]:
    rows = db.execute(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(200)).scalars()
    return [
        {
            "label": r.label,
            "kind": r.kind,
            "base_label": r.base_label,
            "size_bytes": r.size_bytes,
            "targets": r.targets,
            "app_version": r.app_version,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
