"""Weekly summary per editor.

GET    /api/digest                     admin, editor-in-chief: settings and the editors with their address
PUT    /api/digest                     admin, editor-in-chief
GET    /api/digest/preview/{person}    admin, editor-in-chief: last week's summary of one editor (subject + HTML)
POST   /api/digest/test/{person}       admin, editor-in-chief: send that summary to yourself
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Person, User
from ..security import require_role
from ..services import digest as svc
from ..services import mail, settings_store
from .common import audit

router = APIRouter(prefix="/api/digest", tags=["digest"])
can_edit = require_role("admin", "editor_in_chief")


class DigestIn(BaseModel):
    enabled: bool = False
    weekday: int = Field(default=0, ge=0, le=6)
    time: str = "08:00"
    ranking: bool = True
    excluded_person_ids: list[int] = Field(default_factory=list, max_length=1000)

    @field_validator("time")
    @classmethod
    def _time(cls, v: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("invalid_time")
        return v


def _state(db: Session) -> dict:
    cfg = svc.settings(db)
    return {
        "settings": {
            k: cfg.get(k) for k in ("enabled", "weekday", "time", "ranking", "excluded_person_ids", "last_week")
        },
        "editors": svc.editors(db),
        "email_ready": mail.configured(settings_store.get_section(db, "email")),
    }


@router.get("")
def get_digest(db: Session = Depends(get_db), _: User = Depends(can_edit)) -> dict:
    return _state(db)


@router.put("")
def put_digest(body: DigestIn, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    known = set(db.execute(select(Person.id)).scalars())
    changes = body.model_dump()
    changes["excluded_person_ids"] = [i for i in dict.fromkeys(body.excluded_person_ids) if i in known]
    settings_store.update_section(db, svc.KEY, changes)
    audit(db, user, "digest.update", {"enabled": body.enabled})
    return _state(db)


def _person(db: Session, person_id: int) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(404, "not_found")
    return person


@router.get("/preview/{person_id}")
def preview(person_id: int, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    person = _person(db, person_id)
    email, lang = svc.recipient(db, person)
    data = svc.editor_week(db, person)
    msg = svc.build_mail(db, data, email or user.email, lang, bool(svc.settings(db).get("ranking", True)))
    return {"to": email, "language": lang, "subject": msg.subject, "html": msg.html, "data": data}


@router.post("/test/{person_id}")
def send_test(person_id: int, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    person = _person(db, person_id)
    cfg = settings_store.get_section(db, "email")
    if not mail.configured(cfg):
        raise HTTPException(400, "mail_not_configured")
    _, lang = svc.recipient(db, person)
    data = svc.editor_week(db, person)
    try:
        mail.send(
            cfg,
            svc.build_mail(db, data, user.email, user.language or lang, bool(svc.settings(db).get("ranking", True))),
        )
    except mail.MailError as exc:
        raise HTTPException(502, f"mail_failed: {exc}") from exc
    audit(db, user, "digest.test", {"person": person_id})
    return {"ok": True, "to": user.email}
