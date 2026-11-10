"""Saved dashboards and the data for their widgets.

GET    /api/dashboards              everyone: own dashboards and shared ones
POST   /api/dashboards              everyone: a new dashboard (shared only for admin, editor-in-chief)
PUT    /api/dashboards/{id}         its maker, or admin / editor-in-chief for a shared one
DELETE /api/dashboards/{id}         same
GET    /api/dashboards/data         everyone: series for one measure (used by KPI and chart widgets)

A widget is {id, type, title, size, ...}:
  kpi      measure, sources, platforms                        a total with the change against the previous period
  chart    measure, sources, platforms, split, mode, chart    a chart per source/platform or in total
  top      sort, kind, limit                                  the best items (Content)
  editors  limit                                              the editors ranking
  goals                                                       the goals' progress
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Dashboard, User
from ..security import current_user
from ..services import explore
from .common import audit
from .content import Range, period

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])

Measure = Literal["reach", "views", "interactions", "watch_minutes", "followers"]
Split = Literal["none", "platform", "source"]
Platform = Literal[
    "website", "youtube", "facebook", "instagram", "threads", "x", "bluesky", "mastodon", "owncast", "icecast"
]
MANAGES_SHARED = ("admin", "editor_in_chief")


class Widget(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    type: Literal["kpi", "chart", "top", "editors", "goals"]
    title: str = Field(default="", max_length=200)
    size: Literal["small", "half", "full"] = "half"
    measure: Measure = "reach"
    sources: list[int] = Field(default_factory=list, max_length=100)
    platforms: list[Platform] = Field(default_factory=list, max_length=12)
    split: Split = "platform"
    mode: Literal["stacked", "overlay", "separate"] = "stacked"
    chart: Literal["line", "area", "bar"] = "area"
    sort: Literal["views", "reach", "visitors", "shares", "comments", "likes", "minutes", "published"] = "views"
    kind: Literal["", "article", "post", "video", "broadcast", "mount"] = ""
    limit: int = Field(default=10, ge=1, le=50)


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    widgets: list[Widget] = Field(default_factory=list, max_length=40)
    shared: bool = False
    position: int = 0


def _out(d: Dashboard, user: User) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "widgets": d.widgets or [],
        "shared": d.shared,
        "position": d.position,
        "mine": d.created_by == user.id,
        "can_edit": _can_edit(d, user),
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _can_edit(d: Dashboard, user: User) -> bool:
    return d.created_by == user.id or (d.shared and user.role in MANAGES_SHARED)


def _visible(db: Session, user: User):
    return select(Dashboard).where(or_(Dashboard.shared.is_(True), Dashboard.created_by == user.id))


@router.get("")
def list_dashboards(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    rows = db.execute(_visible(db, user).order_by(Dashboard.position, Dashboard.name, Dashboard.id)).scalars()
    return [_out(d, user) for d in rows]


def _check_shared(body: DashboardIn, user: User) -> None:
    if body.shared and user.role not in MANAGES_SHARED:
        raise HTTPException(403, "forbidden")


@router.post("")
def create_dashboard(body: DashboardIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    _check_shared(body, user)
    d = Dashboard(
        name=body.name,
        widgets=[w.model_dump() for w in body.widgets],
        shared=body.shared,
        position=body.position,
        created_by=user.id,
    )
    db.add(d)
    db.commit()
    audit(db, user, "dashboards.create", {"id": d.id, "name": d.name})
    return _out(d, user)


def _get(db: Session, dashboard_id: int, user: User) -> Dashboard:
    d = db.get(Dashboard, dashboard_id)
    if d is None or not (d.shared or d.created_by == user.id):
        raise HTTPException(404, "not_found")
    if not _can_edit(d, user):
        raise HTTPException(403, "forbidden")
    return d


EXAMPLE = [
    {"id": "k1", "type": "kpi", "measure": "reach", "size": "small"},
    {"id": "k2", "type": "kpi", "measure": "views", "size": "small"},
    {"id": "k3", "type": "kpi", "measure": "interactions", "size": "small"},
    {"id": "c1", "type": "chart", "measure": "reach", "split": "platform", "mode": "stacked", "size": "full"},
    {"id": "c2", "type": "chart", "measure": "followers", "split": "source", "mode": "separate", "chart": "line"},
    {"id": "c3", "type": "chart", "measure": "interactions", "split": "platform", "mode": "overlay", "chart": "bar"},
    {"id": "t1", "type": "top", "sort": "views", "limit": 8},
    {"id": "e1", "type": "editors", "limit": 8},
]


def example(name: str, user_id: int | None, shared: bool = False) -> Dashboard:
    """A starting point: total reach, views and interactions, reach per platform, followers, top lists."""
    return Dashboard(
        name=name,
        widgets=[Widget(**w).model_dump() for w in EXAMPLE],
        shared=shared,
        created_by=user_id,
    )


@router.post("/example")
def create_example(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    d = example("Overzicht" if user.language == "nl" else "Overview", user.id)
    db.add(d)
    db.commit()
    audit(db, user, "dashboards.create", {"id": d.id, "name": d.name})
    return _out(d, user)


@router.put("/{dashboard_id}")
def update_dashboard(
    dashboard_id: int, body: DashboardIn, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    d = _get(db, dashboard_id, user)
    if body.shared != d.shared:
        _check_shared(body, user)
    d.name, d.shared, d.position = body.name, body.shared, body.position
    d.widgets = [w.model_dump() for w in body.widgets]
    db.commit()
    audit(db, user, "dashboards.update", {"id": d.id})
    return _out(d, user)


@router.delete("/{dashboard_id}")
def delete_dashboard(dashboard_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    d = _get(db, dashboard_id, user)
    db.delete(d)
    db.commit()
    audit(db, user, "dashboards.delete", {"id": dashboard_id})
    return {"ok": True}


@router.get("/data")
def data(
    measure: Measure = "reach",
    range: Range = "30d",
    split: Split = "platform",
    sources: Annotated[list[int], Query(max_length=100)] = [],  # noqa: B006 - FastAPI query list
    platforms: Annotated[list[Platform], Query(max_length=12)] = [],  # noqa: B006
    compare: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> dict:
    """One measure over a period, with the previous period's total for comparison."""
    level = measure in explore.LEVEL
    span = "7d" if level and range == "24h" else range  # followers are counted per day
    window = period(db, span)
    previous = period(db, span, now=window[0] - timedelta(seconds=1)) if compare else None
    return {"range": span, **measure_data(db, measure, split, sources, list(platforms), window, previous)}


def measure_data(
    db: Session,
    measure: str,
    split: str,
    sources: list[int],
    platforms: list[str],
    window: tuple,
    previous_window: tuple | None,
) -> dict:
    """Series and totals of one measure in a window (start, end, granularity, buckets), with the
    total of an earlier window for comparison. Shared by dashboards and reports."""
    level = measure in explore.LEVEL
    start, end, gran, buckets = window
    chosen = explore.sources_for(db, measure, sources, platforms)
    values = explore.per_source(db, measure, chosen, start, end, gran, buckets)
    series = explore.group(chosen, values, split)
    for s in series:
        s["total"] = explore.total(s["values"], level)
    totals_now = explore.total(
        [
            None if all(v is None for v in col) else sum(v or 0 for v in col)
            for col in zip(*values.values(), strict=True)
        ]
        if values
        else [],
        level,
    )
    previous = None
    if previous_window is not None:
        p_start, p_end, p_gran, p_buckets = previous_window
        p_values = explore.per_source(db, measure, chosen, p_start, p_end, p_gran, p_buckets)
        cols = list(zip(*p_values.values(), strict=True)) if p_values else []
        merged = [None if all(v is None for v in col) else sum(v or 0 for v in col) for col in cols]
        if any(v is not None for v in merged):
            previous = explore.total(merged, level)
    return {
        "measure": measure,
        "kind": "level" if level else "total",
        "granularity": gran,
        "buckets": [b.isoformat() for b in buckets],
        "series": series,
        "daily_only": [s.id for s in chosen if gran == "hour" and s.kind in explore.DAILY_ONLY],
        "total": totals_now,
        "previous": previous,
        "change": None if previous in (None, 0) else round((totals_now - previous) / previous * 100, 1),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
