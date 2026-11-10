"""Goals and followers.

GET    /api/goals                 everyone: goals with their progress
POST   /api/goals                 admin, editor-in-chief
GET    /api/goals/{id}            everyone: progress per day and the target history
PUT    /api/goals/{id}            admin, editor-in-chief: a new target or end date adds a revision
DELETE /api/goals/{id}            admin, editor-in-chief
GET    /api/followers?range=      everyone: followers per source per day
"""

from __future__ import annotations

from datetime import UTC, date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Goal, GoalRevision, MetricPoint, Source, User, utcnow
from ..security import current_user, require_role
from ..services import goals as svc
from ..services.followers import day_bucket
from ..services.rollup import org_timezone
from .common import audit

router = APIRouter(prefix="/api", tags=["goals"])
can_edit = require_role("admin", "editor_in_chief")

Metric = Literal["followers", "views", "reach", "interactions", "watch_minutes"]


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    metric: Metric
    source_ids: list[int] = Field(default_factory=list, max_length=100)
    target: float = Field(gt=0, lt=1e12)
    start_date: date
    end_date: date | None = None
    notify: bool = False
    notify_emails: list[EmailStr] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=500)  # why the target changed
    archived: bool = False

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_before_start")
        return self


def _out(db: Session, goal: Goal, detail: bool = False) -> dict:
    p = svc.progress(db, goal)
    sources = {s.id: s for s in db.execute(select(Source)).scalars()}
    out = {
        "id": goal.id,
        "name": goal.name,
        "metric": goal.metric,
        "source_ids": goal.source_ids or [],
        "sources": [
            {"id": sources[i].id, "name": sources[i].name, "kind": sources[i].kind}
            for i in goal.source_ids or []
            if i in sources
        ],
        "target": goal.target,
        "start_date": goal.start_date.isoformat(),
        "end_date": goal.end_date.isoformat() if goal.end_date else None,
        "notify": goal.notify,
        "notify_emails": goal.notify_emails or [],
        "archived": goal.archived,
        "reached_at": goal.reached_at.isoformat() if goal.reached_at else None,
        **{k: v for k, v in p.items() if detail or k not in ("days", "values", "targets")},
    }
    if detail:
        users = {u.id: u.display_name for u in db.execute(select(User)).scalars()}
        out["revisions"] = [
            {
                "target": r.target,
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "note": r.note,
                "changed_by": users.get(r.changed_by),
                "changed_at": r.changed_at.isoformat(),
            }
            for r in svc.revisions(db, goal)
        ]
    elif p["values"]:
        out["spark"] = p["values"][-30:]
    return out


def _check_sources(db: Session, ids: list[int]) -> None:
    if ids and len(set(db.execute(select(Source.id).where(Source.id.in_(ids))).scalars())) != len(set(ids)):
        raise HTTPException(400, "unknown_source")


@router.get("/goals")
def list_goals(archived: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    rows = db.execute(select(Goal).where(Goal.archived.is_(archived)).order_by(Goal.end_date, Goal.name)).scalars()
    return [_out(db, g) for g in rows]


@router.post("/goals")
def create_goal(body: GoalIn, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    _check_sources(db, body.source_ids)
    goal = Goal(**body.model_dump(exclude={"note"}), created_by=user.id)
    goal.notify_emails = [str(e) for e in body.notify_emails]
    db.add(goal)
    db.flush()
    db.add(
        GoalRevision(goal_id=goal.id, target=goal.target, end_date=goal.end_date, note=body.note, changed_by=user.id)
    )
    db.commit()
    audit(db, user, "goals.create", {"id": goal.id, "name": goal.name})
    return _out(db, goal, detail=True)


def _get(db: Session, goal_id: int) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "not_found")
    return goal


@router.get("/goals/{goal_id}")
def get_goal(goal_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    return _out(db, _get(db, goal_id), detail=True)


@router.put("/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalIn, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    goal = _get(db, goal_id)
    _check_sources(db, body.source_ids)
    changed = goal.target != body.target or goal.end_date != body.end_date
    if goal.metric != body.metric or goal.start_date != body.start_date or goal.source_ids != body.source_ids:
        goal.reached_at = None  # measured differently now
    for k, v in body.model_dump(exclude={"note", "notify_emails"}).items():
        setattr(goal, k, v)
    goal.notify_emails = [str(e) for e in body.notify_emails]
    if changed:
        goal.reached_at = None  # a new target can be reached (and announced) again
        goal.behind_notified_at = None
        db.add(
            GoalRevision(
                goal_id=goal.id, target=body.target, end_date=body.end_date, note=body.note, changed_by=user.id
            )
        )
    db.commit()
    audit(db, user, "goals.update", {"id": goal.id, "target": goal.target})
    return _out(db, goal, detail=True)


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    goal = _get(db, goal_id)
    db.delete(goal)
    db.commit()
    audit(db, user, "goals.delete", {"id": goal_id})
    return {"ok": True}


# ----------------------------------------------------------------------------- followers

GAUGES = {"youtube": "yt_subscribers", "facebook": "fb_followers", "instagram": "ig_followers"}
GAINED = {"youtube": "yt_subs_gained", "facebook": "fb_follows", "instagram": "ig_follows"}
FollowRange = Literal["30d", "90d", "365d"]


@router.get("/followers")
def followers(
    span: FollowRange = Query("90d", alias="range"), db: Session = Depends(get_db), _: User = Depends(current_user)
) -> dict:
    """Followers per day per source (YouTube subscribers, Facebook and Instagram followers)."""
    tz = org_timezone(db)
    today = utcnow().astimezone(tz).date()
    first = today - timedelta(days=int(span[:-1]) - 1)
    days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    index = {d: i for i, d in enumerate(days)}
    out = []
    for s in db.execute(select(Source).where(Source.kind.in_(GAUGES)).order_by(Source.kind, Source.name)).scalars():
        values: list[float | None] = [None] * len(days)
        gained = 0.0
        for bucket, metric, value in db.execute(
            select(MetricPoint.bucket, MetricPoint.metric, MetricPoint.value).where(
                MetricPoint.source_id == s.id,
                MetricPoint.item_id.is_(None),
                MetricPoint.granularity == "day",
                MetricPoint.metric.in_((GAUGES[s.kind], GAINED[s.kind])),
                MetricPoint.bucket >= day_bucket(first, tz),
            )
        ).all():
            b = bucket if bucket.tzinfo else bucket.replace(tzinfo=UTC)
            i = index.get(b.astimezone(tz).date())
            if i is None:
                continue
            if metric == GAUGES[s.kind]:
                values[i] = value
            else:
                gained += value
        known = [v for v in values if v is not None]
        current = (s.config or {}).get("subscribers" if s.kind == "youtube" else "followers")
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "current": current if current is not None else (known[-1] if known else None),
                "change": round(known[-1] - known[0]) if len(known) >= 2 else 0,
                "gained": round(gained),
                "values": values,
            }
        )
    total = (
        [
            sum(v for v in col if v is not None) if any(v is not None for v in col) else None
            for col in zip(*[s["values"] for s in out], strict=True)
        ]
        if out
        else []
    )
    return {
        "range": span,
        "days": [d.isoformat() for d in days],
        "sources": out,
        "total": sum(s["current"] or 0 for s in out),
        "total_change": sum(s["change"] for s in out),
        "total_values": total,
    }
