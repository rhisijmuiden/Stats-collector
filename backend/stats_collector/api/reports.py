"""Reports: compose, generate, send on demand or on a schedule, and the archive.

GET    /api/reports                       editors and up: reports (an editor sees their own)
GET    /api/reports/recipients            admin, editor-in-chief: users to pick as recipients
POST   /api/reports                       editors and up
PUT    /api/reports/{id}                  its maker, or admin / editor-in-chief
DELETE /api/reports/{id}                  same
POST   /api/reports/{id}/generate         same: freeze the report now; returns the run and its link
POST   /api/reports/{id}/send             admin, editor-in-chief: generate and email to the recipients
GET    /api/reports/{id}/runs             same as edit: the archive
GET    /api/reports/runs/{run_id}         same as edit: one archived report
GET    /api/reports/runs/{run_id}/pdf     same as edit
GET    /api/public/reports/{token}        anyone with the link, until it expires
GET    /api/public/reports/{token}/pdf    same

A report has the blocks of a dashboard (kpi, chart, top, editors, goals) plus text blocks. Editors
cannot add the editors ranking, schedule a report or send it. A report with the editors ranking can
only go to editors-in-chief and administrators.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Report, ReportRun, User, utcnow
from ..security import decrypt_secret, require_role
from ..services import reports as svc
from ..services.rollup import org_timezone
from .common import audit
from .dashboards import Widget

router = APIRouter(tags=["reports"])
may_report = require_role("admin", "editor_in_chief", "editor")
MANAGES = ("admin", "editor_in_chief")


class Block(Widget):
    type: Literal["kpi", "chart", "top", "editors", "goals", "text"]  # type: ignore[assignment]
    text: str = Field(default="", max_length=5000)


class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    intro: str = Field(default="", max_length=5000)
    blocks: list[Block] = Field(default_factory=list, max_length=40)
    period: Literal["yesterday", "last_week", "last_month", "last_7d", "last_30d", "last_90d"] = "last_month"
    language: Literal["en", "nl"] = "en"
    schedule: Literal["none", "daily", "weekly", "monthly"] = "none"
    send_time: str = "08:00"
    weekday: int = Field(default=0, ge=0, le=6)
    monthday: int = Field(default=1, ge=1, le=28)
    recipient_users: list[int] = Field(default_factory=list, max_length=200)
    recipient_emails: list[EmailStr] = Field(default_factory=list, max_length=200)
    attach_pdf: bool = True
    link_days: int = Field(default=30, ge=1, le=365)
    enabled: bool = True

    @field_validator("send_time")
    @classmethod
    def _time(cls, v: str) -> str:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", v.strip())
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            raise ValueError("invalid_time")
        return f"{int(m[1]):02d}:{m[2]}"


def _can_edit(r: Report, user: User) -> bool:
    return user.role in MANAGES or r.created_by == user.id


def _run_out(run: ReportRun) -> dict:
    valid = svc._aware(run.expires_at) > utcnow()
    token = decrypt_secret(run.token_enc) if valid else None
    return {
        "id": run.id,
        "report_id": run.report_id,
        "title": run.title,
        "start": run.period_start.isoformat(),
        "end": run.period_end.isoformat(),
        "created_at": run.created_at.isoformat(),
        "trigger": run.trigger,
        "status": run.status,
        "sent_at": run.sent_at.isoformat() if run.sent_at else None,
        "recipients": run.recipients or [],
        "error": run.error,
        "expires_at": run.expires_at.isoformat(),
        "link": svc.link(token) if token else None,
    }


def _out(db: Session, r: Report, user: User) -> dict:
    last = db.execute(
        select(ReportRun).where(ReportRun.report_id == r.id).order_by(ReportRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    return {
        "id": r.id,
        "name": r.name,
        "title": r.title,
        "intro": r.intro,
        "blocks": r.blocks or [],
        "period": r.period,
        "language": r.language,
        "schedule": r.schedule,
        "send_time": r.send_time,
        "weekday": r.weekday,
        "monthday": r.monthday,
        "recipient_users": r.recipient_users or [],
        "recipient_emails": r.recipient_emails or [],
        "attach_pdf": r.attach_pdf,
        "link_days": r.link_days,
        "enabled": r.enabled,
        "next_run_at": r.next_run_at.isoformat() if r.next_run_at else None,
        "mine": r.created_by == user.id,
        "can_send": user.role in MANAGES,
        "last_run": _run_out(last) if last else None,
    }


def _get(db: Session, report_id: int, user: User) -> Report:
    r = db.get(Report, report_id)
    if r is None or not _can_edit(r, user):
        raise HTTPException(404, "not_found")
    return r


def _apply(db: Session, r: Report, body: ReportIn, user: User) -> None:
    if user.role not in MANAGES:
        if any(b.type == "editors" for b in body.blocks):
            raise HTTPException(403, "editors_block_forbidden")
        if body.schedule != "none" or body.recipient_users or body.recipient_emails:
            raise HTTPException(403, "forbidden")
    if body.recipient_users:
        known = set(db.execute(select(User.id).where(User.id.in_(body.recipient_users))).scalars())
        if known != set(body.recipient_users):
            raise HTTPException(400, "unknown_user")
    for k, v in body.model_dump(exclude={"blocks", "recipient_emails"}).items():
        setattr(r, k, v)
    r.blocks = [b.model_dump() for b in body.blocks]
    r.recipient_emails = sorted({str(e).lower() for e in body.recipient_emails})
    if not svc.editors_ok(db, r):
        raise HTTPException(400, "editors_recipients")
    if r.schedule != "none" and not (r.recipient_users or r.recipient_emails):
        raise HTTPException(400, "no_recipients")
    r.next_run_at = svc.next_run(r, utcnow(), org_timezone(db))


@router.get("/api/reports")
def list_reports(db: Session = Depends(get_db), user: User = Depends(may_report)) -> list[dict]:
    stmt = select(Report).order_by(Report.name, Report.id)
    if user.role not in MANAGES:
        stmt = stmt.where(Report.created_by == user.id)
    return [_out(db, r, user) for r in db.execute(stmt).scalars()]


@router.get("/api/reports/recipients")
def recipient_options(
    db: Session = Depends(get_db), _: User = Depends(require_role("admin", "editor_in_chief"))
) -> list[dict]:
    users = db.execute(select(User).where(User.is_active.is_(True)).order_by(User.display_name)).scalars()
    return [{"id": u.id, "name": u.display_name, "email": u.email, "role": u.role} for u in users]


@router.post("/api/reports")
def create_report(body: ReportIn, db: Session = Depends(get_db), user: User = Depends(may_report)) -> dict:
    r = Report(created_by=user.id)
    _apply(db, r, body, user)
    db.add(r)
    db.commit()
    audit(db, user, "reports.create", {"id": r.id, "name": r.name})
    return _out(db, r, user)


@router.put("/api/reports/{report_id}")
def update_report(
    report_id: int, body: ReportIn, db: Session = Depends(get_db), user: User = Depends(may_report)
) -> dict:
    r = _get(db, report_id, user)
    _apply(db, r, body, user)
    db.commit()
    audit(db, user, "reports.update", {"id": r.id})
    return _out(db, r, user)


@router.delete("/api/reports/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(may_report)) -> dict:
    r = _get(db, report_id, user)
    db.delete(r)
    db.commit()
    audit(db, user, "reports.delete", {"id": report_id})
    return {"ok": True}


@router.post("/api/reports/{report_id}/generate")
def generate(report_id: int, db: Session = Depends(get_db), user: User = Depends(may_report)) -> dict:
    r = _get(db, report_id, user)
    run, _ = svc.generate(db, r, user.id)
    audit(db, user, "reports.generate", {"id": r.id, "run": run.id})
    return _run_out(run)


@router.post("/api/reports/{report_id}/send")
def send_now(
    report_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "editor_in_chief"))
) -> dict:
    r = _get(db, report_id, user)
    if not svc.editors_ok(db, r):
        raise HTTPException(400, "editors_recipients")
    if not svc.recipients(db, r):
        raise HTTPException(400, "no_recipients")
    run, token = svc.generate(db, r, user.id)
    try:
        svc.send(db, r, run, token)
    except svc.ReportError as exc:
        run.status, run.error = "failed", str(exc)
        db.commit()
        raise HTTPException(400, str(exc)) from exc
    audit(db, user, "reports.send", {"id": r.id, "run": run.id, "to": run.recipients})
    if run.status == "failed":
        raise HTTPException(502, f"mail_failed: {run.error}")
    return _run_out(run)


@router.get("/api/reports/{report_id}/runs")
def runs(report_id: int, db: Session = Depends(get_db), user: User = Depends(may_report)) -> list[dict]:
    r = _get(db, report_id, user)
    rows = db.execute(
        select(ReportRun).where(ReportRun.report_id == r.id).order_by(ReportRun.id.desc()).limit(200)
    ).scalars()
    return [_run_out(x) for x in rows]


def _own_run(db: Session, run_id: int, user: User) -> ReportRun:
    run = db.get(ReportRun, run_id)
    if run is None:
        raise HTTPException(404, "not_found")
    if user.role not in MANAGES:
        r = db.get(Report, run.report_id) if run.report_id else None
        if r is None or r.created_by != user.id:
            raise HTTPException(404, "not_found")
    return run


def _view(run: ReportRun) -> dict:
    return {**(run.data or {}), "expires_at": run.expires_at.isoformat(), "run_id": run.id}


@router.get("/api/reports/runs/{run_id}")
def run_detail(run_id: int, db: Session = Depends(get_db), user: User = Depends(may_report)) -> dict:
    return _view(_own_run(db, run_id, user))


def _pdf_response(run: ReportRun, token: str | None) -> Response:
    path = svc.pdf_file(run)
    if path.exists():
        data = path.read_bytes()
    elif token is None:
        raise HTTPException(410, "link_expired")
    else:
        try:
            data = svc.render_pdf(run, token)
        except svc.ReportError as exc:
            raise HTTPException(503, str(exc)) from exc
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "", run.title or "report").strip() or "report"
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"', "Cache-Control": "private, no-store"},
    )


@router.get("/api/reports/runs/{run_id}/pdf")
def run_pdf(run_id: int, db: Session = Depends(get_db), user: User = Depends(may_report)) -> Response:
    run = _own_run(db, run_id, user)
    valid = svc._aware(run.expires_at) > utcnow()
    return _pdf_response(run, decrypt_secret(run.token_enc) if valid else None)


def _public(db: Session, token: str) -> ReportRun:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", token):
        raise HTTPException(404, "not_found")
    run = svc.find_run(db, token)
    if run is None:
        raise HTTPException(404, "not_found")
    if svc._aware(run.expires_at) <= utcnow():
        raise HTTPException(410, "link_expired")
    return run


@router.get("/api/public/reports/{token}")
def public_report(token: str, db: Session = Depends(get_db)) -> dict:
    return _view(_public(db, token))


@router.get("/api/public/reports/{token}/pdf")
def public_pdf(token: str, db: Session = Depends(get_db)) -> Response:
    return _pdf_response(_public(db, token), token)
