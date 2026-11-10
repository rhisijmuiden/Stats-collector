from __future__ import annotations

import json
import platform
import shutil
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import build_info
from ..config import get_settings
from ..db import get_db
from ..models import OpsJob, User
from ..security import current_user, require_admin
from ..services import ops, settings_store, updates
from .common import audit

router = APIRouter(prefix="/api/system", tags=["system"])


def job_out(job: OpsJob, with_log: bool = False) -> dict:
    out = {
        "id": job.id,
        "kind": job.kind,
        "params": job.params,
        "status": job.status,
        "result": job.result,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
    if with_log:
        out["log"] = job.log
    return out


def _db_version(db: Session) -> str | None:
    try:
        if db.bind.dialect.name == "postgresql":
            return db.execute(text("SHOW server_version")).scalar()
        return "SQLite " + db.execute(text("select sqlite_version()")).scalar()
    except Exception:  # noqa: BLE001
        return None


def _disk() -> dict | None:
    try:
        usage = shutil.disk_usage(get_settings().data_dir)
        return {"total": usage.total, "free": usage.free}
    except OSError:
        return None


@router.get("/info")
def info(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    channel = settings_store.get_section(db, "updates")["channel"]
    data = {
        "build": build_info(),
        "channel": channel,
        "python": platform.python_version(),
    }
    if user.role == "admin":
        data.update(
            {
                "database": _db_version(db),
                "os": platform.platform(),
                "disk": _disk(),
                "jobs": [job_out(j) for j in db.execute(select(OpsJob).order_by(OpsJob.id.desc()).limit(5)).scalars()],
            }
        )
    return data


@router.get("/releases")
def releases(force: bool = False, db: Session = Depends(get_db), _=Depends(current_user)) -> dict:
    channel = settings_store.get_section(db, "updates")["channel"]
    try:
        all_releases = updates.fetch_releases(force=force)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"github_unreachable: {exc}") from exc
    return {
        "channel": channel,
        "check": updates.check(channel, all_releases),
        "releases": [r.to_dict() for r in all_releases],
    }


class ChannelIn(BaseModel):
    channel: Literal["production", "test"]


@router.put("/channel")
def set_channel(body: ChannelIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    settings_store.update_section(db, "updates", {"channel": body.channel})
    audit(db, admin, "system.channel", {"channel": body.channel})
    return {"channel": body.channel}


class UpdateIn(BaseModel):
    version: str


def _busy(db: Session) -> bool:
    return (
        db.execute(select(OpsJob).where(OpsJob.status.in_(("queued", "running"))).limit(1)).scalar_one_or_none()
        is not None
    )


@router.post("/update", status_code=202)
def start_update(body: UpdateIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    if _busy(db):
        raise HTTPException(409, "job_running")
    try:
        job = ops.enqueue(db, "update", {"version": body.version}, admin)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, admin, "system.update", {"version": body.version})
    return job_out(job)


@router.get("/jobs")
def jobs(db: Session = Depends(get_db), _=Depends(require_admin)) -> list[dict]:
    return [job_out(j) for j in db.execute(select(OpsJob).order_by(OpsJob.id.desc()).limit(50)).scalars()]


@router.get("/jobs/{job_id}")
def job(job_id: int, db: Session = Depends(get_db), _=Depends(require_admin)) -> dict:
    j = db.get(OpsJob, job_id)
    if j is None:
        # The database may have been restored; fall back to the job log file.
        path = get_settings().ops_dir / f"job-{job_id}.log"
        if path.is_file():
            return {"id": job_id, "status": "unknown", "log": path.read_text()}
        raise HTTPException(404, "not_found")
    return job_out(j, with_log=True)


@router.get("/last/{kind}")
def last(kind: Literal["update", "backup", "restore"], _=Depends(require_admin)) -> dict:
    path = get_settings().ops_dir / f"last-{kind}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}
