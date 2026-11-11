"""Alerts on outliers and best posting times.

GET    /api/alerts                 admin, editor-in-chief, editor: rules and the latest alerts
POST   /api/alerts                 admin, editor-in-chief
PUT    /api/alerts/{id}            admin, editor-in-chief (an empty teams_webhook keeps the stored one)
DELETE /api/alerts/{id}            admin, editor-in-chief
POST   /api/alerts/{id}/test       admin, editor-in-chief: send a test message
POST   /api/alerts/check           admin, editor-in-chief: look for outliers now
GET    /api/best-times?source_id=&days=   everyone: the best hours of the week for one channel
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AlertRule, Source, User, utcnow
from ..security import current_user, encrypt_secret, require_role
from ..services import alerts as svc
from ..services.besttimes import best_times
from .common import audit

router = APIRouter(prefix="/api", tags=["insights"])
can_edit = require_role("admin", "editor_in_chief")
can_view = require_role("admin", "editor_in_chief", "editor")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scope: Literal["item", "channel"] = "item"
    source_ids: list[int] = Field(default_factory=list, max_length=100)
    factor: float = Field(default=3.0, ge=1.2, le=100)
    min_value: float = Field(default=500, ge=0, lt=1e12)
    teams_webhook: str | None = Field(default=None, max_length=2000)  # None/"" = keep, "-" = remove
    emails: list[EmailStr] = Field(default_factory=list, max_length=20)
    language: Literal["en", "nl"] = "en"
    quiet_start: str = ""
    quiet_end: str = ""
    enabled: bool = True

    @field_validator("teams_webhook")
    @classmethod
    def _https(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if v and v != "-" and not v.startswith("https://"):
            raise ValueError("webhook_must_be_https")
        return v or None

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def _time(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not HHMM.match(v):
            raise ValueError("invalid_time")
        return v


def _out(rule: AlertRule, sources: dict[int, Source], counts: dict[int, int]) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "scope": rule.scope,
        "source_ids": [int(i) for i in rule.source_ids or []],
        "sources": [
            {"id": i, "name": sources[i].name, "kind": sources[i].kind} for i in rule.source_ids or [] if i in sources
        ],
        "factor": rule.factor,
        "min_value": rule.min_value,
        "teams_webhook_set": bool(rule.teams_webhook_enc),
        "emails": rule.emails or [],
        "language": rule.language,
        "quiet_start": rule.quiet_start,
        "quiet_end": rule.quiet_end,
        "enabled": rule.enabled,
        "alerts_7d": counts.get(rule.id, 0),
    }


def _check_sources(db: Session, ids: list[int]) -> None:
    if ids and len(set(db.execute(select(Source.id).where(Source.id.in_(ids))).scalars())) != len(set(ids)):
        raise HTTPException(400, "unknown_source")


def _apply(rule: AlertRule, body: RuleIn) -> None:
    for k, v in body.model_dump(exclude={"teams_webhook", "emails"}).items():
        setattr(rule, k, v)
    rule.emails = [str(e) for e in body.emails]
    if body.teams_webhook == "-":
        rule.teams_webhook_enc = None
    elif body.teams_webhook:
        rule.teams_webhook_enc = encrypt_secret(body.teams_webhook)


def _get(db: Session, rule_id: int) -> AlertRule:
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(404, "not_found")
    return rule


def _sources(db: Session) -> dict[int, Source]:
    return {s.id: s for s in db.execute(select(Source)).scalars()}


@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db), _: User = Depends(can_view)) -> dict:
    sources = _sources(db)
    counts = svc.counts_by_rule(db, utcnow() - timedelta(days=7))
    rules = db.execute(select(AlertRule).order_by(AlertRule.name)).scalars()
    return {"rules": [_out(r, sources, counts) for r in rules], "events": svc.recent(db)}


@router.post("/alerts")
def create_alert(body: RuleIn, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    _check_sources(db, body.source_ids)
    rule = AlertRule(created_by=user.id)
    _apply(rule, body)
    db.add(rule)
    db.commit()
    audit(db, user, "alerts.create", {"id": rule.id, "name": rule.name})
    return _out(rule, _sources(db), {})


@router.put("/alerts/{rule_id}")
def update_alert(rule_id: int, body: RuleIn, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    rule = _get(db, rule_id)
    _check_sources(db, body.source_ids)
    _apply(rule, body)
    db.commit()
    audit(db, user, "alerts.update", {"id": rule.id})
    return _out(rule, _sources(db), svc.counts_by_rule(db, utcnow() - timedelta(days=7)))


@router.delete("/alerts/{rule_id}")
def delete_alert(rule_id: int, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    rule = _get(db, rule_id)
    db.delete(rule)
    db.commit()
    audit(db, user, "alerts.delete", {"id": rule_id})
    return {"ok": True}


@router.post("/alerts/{rule_id}/test")
def test_alert(rule_id: int, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    rule = _get(db, rule_id)
    if not rule.teams_webhook_enc and not rule.emails:
        raise HTTPException(400, "alert_no_destination")
    done, error = svc.test(db, rule)
    audit(db, user, "alerts.test", {"id": rule.id, "delivered": done})
    return {"delivered": done, "error": error}


@router.post("/alerts/check")
def check_now(db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    found = svc.check(db)
    return {"found": found, "events": svc.recent(db)}


@router.get("/best-times")
def get_best_times(
    source_id: int,
    days: int = Query(90, ge=14, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "not_found")
    if source.kind in ("icecast", "owncast"):
        raise HTTPException(400, "best_times_no_items")
    return best_times(db, source, days)
