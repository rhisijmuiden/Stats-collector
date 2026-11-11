"""Content (top lists per article, broadcast and mount) and editor performance.

Editor names and per-editor numbers are removed here, on the server, for roles that may not see
them: Admin and Editor-in-chief see everyone, an Editor sees only their own numbers, Staff none.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ContentItem, DimensionPoint, ItemLink, ItemPerson, MetricPoint, Person, Source, User, utcnow
from ..security import current_user, require_role
from ..services import links as link_svc
from ..services.metrics import (
    BSKY_LIKES,
    BSKY_QUOTES,
    BSKY_REPLIES,
    BSKY_REPOSTS,
    FB_CLICKS,
    FB_COMMENTS,
    FB_REACH,
    FB_REACTIONS,
    FB_SHARES,
    FB_VIEWS,
    IG_COMMENTS,
    IG_LIKES,
    IG_REACH,
    IG_SAVES,
    IG_SHARES,
    IG_VIEWS,
    LIVE_MINUTES,
    LIVE_PEAK,
    MASTO_BOOSTS,
    MASTO_FAVOURITES,
    MASTO_REPLIES,
    TH_LIKES,
    TH_QUOTES,
    TH_REPLIES,
    TH_REPOSTS,
    TH_SHARES,
    TH_VIEWS,
    WEB_COMMENTS,
    WEB_READ_SECONDS,
    WEB_READS,
    WEB_SHARES,
    WEB_VIEWS,
    WEB_VISITORS,
    X_BOOKMARKS,
    X_IMPRESSIONS,
    X_LIKES,
    X_LINK_CLICKS,
    X_QUOTES,
    X_REPLIES,
    X_REPOSTS,
    YT_COMMENTS,
    YT_LIKES,
    YT_SHARES,
    YT_VIEWS,
    YT_WATCH_MINUTES,
)
from ..services.rollup import hour_floor, local_day_start, next_local_day, org_timezone
from .common import audit

router = APIRouter(prefix="/api", tags=["content"])

Range = Literal["24h", "7d", "30d", "90d", "365d"]
SortKey = Literal[
    "views",
    "visitors",
    "reach",
    "read_seconds",
    "reads",
    "shares",
    "comments",
    "likes",
    "saves",
    "clicks",
    "minutes",
    "peak",
    "published",
]
# Platform metrics shown under one common name: views are page, video or post views, minutes are
# listening, viewing (live) or YouTube watch minutes, likes include Facebook reactions. An item
# belongs to one platform, so nothing is counted twice.
METRIC_NAMES = {
    WEB_VIEWS: "views",
    YT_VIEWS: "views",
    FB_VIEWS: "views",
    IG_VIEWS: "views",
    WEB_VISITORS: "visitors",
    FB_REACH: "reach",
    IG_REACH: "reach",
    WEB_READ_SECONDS: "read_seconds",
    WEB_READS: "reads",
    WEB_SHARES: "shares",
    YT_SHARES: "shares",
    FB_SHARES: "shares",
    IG_SHARES: "shares",
    WEB_COMMENTS: "comments",
    YT_COMMENTS: "comments",
    FB_COMMENTS: "comments",
    IG_COMMENTS: "comments",
    YT_LIKES: "likes",
    FB_REACTIONS: "likes",
    IG_LIKES: "likes",
    IG_SAVES: "saves",
    TH_VIEWS: "views",
    X_IMPRESSIONS: "views",
    X_LIKES: "likes",
    X_REPOSTS: "shares",
    X_QUOTES: "shares",
    X_REPLIES: "comments",
    X_BOOKMARKS: "saves",
    X_LINK_CLICKS: "clicks",
    TH_LIKES: "likes",
    TH_REPOSTS: "shares",
    TH_QUOTES: "shares",
    TH_SHARES: "shares",
    TH_REPLIES: "comments",
    BSKY_LIKES: "likes",
    MASTO_FAVOURITES: "likes",
    BSKY_REPOSTS: "shares",
    BSKY_QUOTES: "shares",
    MASTO_BOOSTS: "shares",
    BSKY_REPLIES: "comments",
    MASTO_REPLIES: "comments",
    FB_CLICKS: "clicks",
    LIVE_MINUTES: "minutes",
    YT_WATCH_MINUTES: "minutes",
    LIVE_PEAK: "peak",
}
TOTALS = tuple(dict.fromkeys(METRIC_NAMES.values()))
SEES_ALL = ("admin", "editor_in_chief")
can_link = require_role("admin", "editor_in_chief", "editor")
SOCIAL_SOURCES = ("facebook", "instagram", "threads", "x", "youtube", "bluesky", "mastodon")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def period(db: Session, r: str, now: datetime | None = None) -> tuple[datetime, datetime, str, list[datetime]]:
    """(start, end, granularity, buckets) for a range: hours for 24h, local days otherwise."""
    now = now or utcnow()
    if r == "24h":
        end = hour_floor(now) + timedelta(hours=1)
        start = end - timedelta(hours=24)
        return start, end, "hour", [start + timedelta(hours=i) for i in range(24)]
    tz = org_timezone(db)
    days = int(r.rstrip("d"))
    end = next_local_day(local_day_start(now, tz), tz)
    start = local_day_start(end - timedelta(days=days, hours=-12), tz)
    buckets, day = [], start
    while day < end:
        buckets.append(day)
        day = next_local_day(day, tz)
    return start, end, "day", buckets


def own_person(db: Session, user: User) -> Person | None:
    return db.execute(select(Person).where(Person.user_id == user.id).order_by(Person.id)).scalars().first()


def _people_for(db: Session, item_ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    if not item_ids:
        return out
    rows = db.execute(
        select(ItemPerson.item_id, ItemPerson.role, Person.id, Person.display_name)
        .join(Person, Person.id == ItemPerson.person_id)
        .where(ItemPerson.item_id.in_(list(item_ids)))
        .order_by(ItemPerson.role)
    ).all()
    for item_id, role, pid, name in rows:
        out[item_id].append({"id": pid, "name": name, "role": role})
    return out


def _totals(db: Session, start: datetime, end: datetime, gran: str, item_ids=None) -> dict[int, dict]:
    q = (
        select(MetricPoint.item_id, MetricPoint.metric, func.sum(MetricPoint.value), func.max(MetricPoint.value))
        .where(
            MetricPoint.item_id.is_not(None),
            MetricPoint.granularity == gran,
            MetricPoint.bucket >= start,
            MetricPoint.bucket < end,
            MetricPoint.metric.in_(tuple(METRIC_NAMES)),
        )
        .group_by(MetricPoint.item_id, MetricPoint.metric)
    )
    if item_ids is not None:
        q = q.where(MetricPoint.item_id.in_(list(item_ids)))
    out: dict[int, dict] = defaultdict(dict)
    for item_id, metric, total, peak in db.execute(q).all():
        name = METRIC_NAMES[metric]
        value = float(peak if metric == LIVE_PEAK else total or 0)
        out[item_id][name] = round(out[item_id].get(name, 0) + value, 2)
    return out


def _item_out(item: ContentItem, source: Source | None, metrics: dict, authors: list[dict] | None) -> dict:
    views = metrics.get("views", 0)
    out = {
        "id": item.id,
        "title": item.title,
        "kind": item.kind,
        "url": item.url,
        "category": item.category,
        "tags": item.tags or [],
        "source": {"id": source.id, "name": source.name, "kind": source.kind} if source else None,
        "published_at": _aware(item.published_at).isoformat() if item.published_at else None,
        "ended_at": _aware(item.ended_at).isoformat() if item.ended_at else None,
        "metrics": {k: metrics.get(k, 0) for k in TOTALS},
        "avg_read_seconds": round(metrics.get("read_seconds", 0) / views, 1) if views else 0,
        # YouTube: average view duration = watch time / views
        "avg_watch_seconds": round(metrics.get("minutes", 0) * 60 / views, 1)
        if views and source is not None and source.kind == "youtube"
        else 0,
        "comments_total": int((item.meta or {}).get("comments", 0)),
        "reactions": (item.meta or {}).get("reactions") or None,  # Facebook: per type
    }
    if authors is not None:
        out["authors"] = authors
    return out


def _check_person_access(db: Session, user: User, person_id: int) -> None:
    if user.role in SEES_ALL:
        return
    me = own_person(db, user) if user.role == "editor" else None
    if me is None or me.id != person_id:
        raise HTTPException(403, "forbidden")


@router.get("/content/filters")
def filters(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    sources = db.execute(select(Source).order_by(Source.kind, Source.name)).scalars()
    cats = db.execute(
        select(ContentItem.category).where(ContentItem.category.is_not(None)).distinct().order_by(ContentItem.category)
    ).scalars()
    people: list[dict] = []
    if user.role in SEES_ALL:
        people = [
            {"id": p.id, "name": p.display_name}
            for p in db.execute(select(Person).order_by(Person.display_name)).scalars()
        ]
    elif user.role == "editor" and (me := own_person(db, user)):
        people = [{"id": me.id, "name": me.display_name}]
    return {
        "sources": [{"id": s.id, "name": s.name, "kind": s.kind} for s in sources],
        "categories": [c for c in cats if c],
        "people": people,
        "can_see_editors": user.role in SEES_ALL,
    }


@router.get("/content/top")
def top(
    range: Range = "7d",
    sort: SortKey = "views",
    source: int | None = None,
    kind: str | None = Query(default=None, max_length=32),
    category: str | None = Query(default=None, max_length=200),
    person: int | None = None,
    via: Literal["own", "social"] = "own",
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    start, end, gran, _ = period(db, range)
    if person is not None:
        _check_person_access(db, user, person)
    stmt = select(ContentItem)
    if source is not None:
        stmt = stmt.where(ContentItem.source_id == source)
    if kind:
        stmt = stmt.where(ContentItem.kind == kind)
    if category:
        stmt = stmt.where(ContentItem.category == category)
    if q:
        stmt = stmt.where(ContentItem.title.ilike(f"%{q.strip()}%"))
    if person is not None:
        own = select(ItemPerson.item_id).where(ItemPerson.person_id == person)
        if via == "social":  # the posts and videos that link to this editor's articles
            own = select(ItemLink.from_item_id).where(ItemLink.to_item_id.in_(own))
        stmt = stmt.where(ContentItem.id.in_(own))
    return {
        "range": range,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sort": sort,
        "items": ranked_items(db, stmt, start, end, gran, sort, limit, user.role in SEES_ALL),
    }


def ranked_items(db: Session, stmt, start: datetime, end: datetime, gran: str, sort: str, limit: int, authors: bool):
    """The items of a query ranked by one metric in a window (or by publication date). Shared with reports."""
    items = {i.id: i for i in db.execute(stmt).scalars()}
    totals = _totals(db, start, end, gran, items.keys())
    if sort == "published":
        candidates = [i for i in items.values() if i.published_at and start <= _aware(i.published_at) < end]
        ranked = sorted(candidates, key=lambda i: _aware(i.published_at), reverse=True)
    else:
        ranked = sorted((items[i] for i in totals if totals[i].get(sort)), key=lambda i: -totals[i.id].get(sort, 0))
    ranked = ranked[:limit]
    sources = {s.id: s for s in db.execute(select(Source)).scalars()}
    people = _people_for(db, [i.id for i in ranked]) if authors else {}
    return [
        _item_out(i, sources.get(i.source_id), totals.get(i.id, {}), people.get(i.id, []) if authors else None)
        for i in ranked
    ]


def _series(db: Session, gran: str, buckets: list[datetime], where) -> dict[str, list[float]]:
    index = {b: n for n, b in enumerate(buckets)}
    out: dict[str, list[float]] = {}
    rows = db.execute(
        select(MetricPoint.metric, MetricPoint.bucket, func.sum(MetricPoint.value), func.max(MetricPoint.value))
        .where(
            *where,
            MetricPoint.granularity == gran,
            MetricPoint.bucket >= buckets[0],
            MetricPoint.metric.in_(tuple(METRIC_NAMES)),
        )
        .group_by(MetricPoint.metric, MetricPoint.bucket)
    ).all()
    for metric, bucket, total, peak in rows:
        n = index.get(_aware(bucket))
        if n is None:
            continue
        name = METRIC_NAMES[metric]
        series = out.setdefault(name, [0.0] * len(buckets))
        series[n] = round(series[n] + float(peak if metric == LIVE_PEAK else total or 0), 2)
    return out


def _dims(db: Session, start: datetime, end: datetime, where) -> dict[str, list[dict]]:
    rows = db.execute(
        select(DimensionPoint.dimension, DimensionPoint.key, func.sum(DimensionPoint.value))
        .where(*where, DimensionPoint.bucket >= start, DimensionPoint.bucket < end)
        .group_by(DimensionPoint.dimension, DimensionPoint.key)
    ).all()
    out: dict[str, list[dict]] = defaultdict(list)
    for dim, key, total in sorted(rows, key=lambda r: -(r[2] or 0)):
        if len(out[dim]) < 15:
            out[dim].append({"key": key, "value": round(float(total or 0), 1)})
    return dict(out)


def _linked(db: Session, item: ContentItem, start: datetime, end: datetime, gran: str) -> list[dict]:
    """Items linked to this one, either way round (a post and its article), with their numbers."""
    rows = db.execute(
        select(ItemLink).where(or_(ItemLink.from_item_id == item.id, ItemLink.to_item_id == item.id))
    ).scalars()
    method = {(link.to_item_id if link.from_item_id == item.id else link.from_item_id): link.method for link in rows}
    if not method:
        return []
    others = list(db.execute(select(ContentItem).where(ContentItem.id.in_(list(method)))).scalars())
    totals = _totals(db, start, end, gran, list(method))
    sources = {s.id: s for s in db.execute(select(Source)).scalars()}
    out = [
        {**_item_out(o, sources.get(o.source_id), totals.get(o.id, {}), None), "method": method[o.id]} for o in others
    ]
    out.sort(key=lambda r: r["published_at"] or "", reverse=True)
    return out


@router.get("/content/find")
def find_items(
    q: str = Query(default="", max_length=200),
    side: Literal["article", "social", "any"] = "article",
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[dict]:
    """Search by title or address, for picking an item to link to."""
    stmt = select(ContentItem)
    if side != "any":  # any: also broadcasts, for stories
        kinds = link_svc.ARTICLE_KINDS if side == "article" else link_svc.SOCIAL_KINDS
        stmt = stmt.where(ContentItem.kind.in_(kinds))
    else:
        stmt = stmt.where(ContentItem.kind != "mount")
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(ContentItem.title.ilike(term), ContentItem.url.ilike(term)))
    rows = db.execute(stmt.order_by(ContentItem.published_at.desc()).limit(20)).scalars()
    sources = {s.id: s for s in db.execute(select(Source)).scalars()}
    return [
        {
            "id": i.id,
            "title": i.title,
            "url": i.url,
            "published_at": _aware(i.published_at).isoformat() if i.published_at else None,
            "source": {"id": i.source_id, "name": sources[i.source_id].name, "kind": sources[i.source_id].kind}
            if i.source_id in sources
            else None,
        }
        for i in rows
    ]


@router.get("/content/{item_id}")
def item_detail(
    item_id: int, range: Range = "30d", db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    item = db.get(ContentItem, item_id)
    if item is None:
        raise HTTPException(404, "not_found")
    start, end, gran, buckets = period(db, range)
    totals = _totals(db, start, end, gran, [item.id]).get(item.id, {})
    show_authors = user.role in SEES_ALL
    authors = _people_for(db, [item.id]).get(item.id, []) if show_authors else None
    return {
        "range": range,
        "granularity": gran,
        "buckets": [b.isoformat() for b in buckets],
        "item": _item_out(item, db.get(Source, item.source_id), totals, authors),
        "series": _series(db, gran, buckets, [MetricPoint.item_id == item.id]),
        "dimensions": _dims(db, start, end, [DimensionPoint.item_id == item.id]),
        "links": _linked(db, item, start, end, gran),
        "can_link": user.role in ("admin", "editor_in_chief", "editor")
        and item.kind in (*link_svc.ARTICLE_KINDS, *link_svc.SOCIAL_KINDS),
    }


class LinkIn(BaseModel):
    item_id: int


def _pair(db: Session, a: int, b: int) -> tuple[ContentItem, ContentItem]:
    """(social item, article) for two item ids given in either order."""
    one, two = db.get(ContentItem, a), db.get(ContentItem, b)
    if one is None or two is None:
        raise HTTPException(404, "not_found")
    if one.kind in link_svc.ARTICLE_KINDS and two.kind in link_svc.SOCIAL_KINDS:
        one, two = two, one
    if one.kind not in link_svc.SOCIAL_KINDS or two.kind not in link_svc.ARTICLE_KINDS:
        raise HTTPException(400, "link_kinds")
    return one, two


@router.post("/content/{item_id}/links")
def add_link(item_id: int, body: LinkIn, db: Session = Depends(get_db), user: User = Depends(can_link)) -> dict:
    social, article = _pair(db, item_id, body.item_id)
    link_svc.add(db, social, article)
    audit(db, user, "content.link", {"from": social.id, "to": article.id})
    return {"ok": True}


@router.delete("/content/{item_id}/links/{other_id}")
def remove_link(item_id: int, other_id: int, db: Session = Depends(get_db), user: User = Depends(can_link)) -> dict:
    social, article = _pair(db, item_id, other_id)
    if not link_svc.remove(db, social, article):
        raise HTTPException(404, "not_found")
    audit(db, user, "content.unlink", {"from": social.id, "to": article.id})
    return {"ok": True}


# ----------------------------------------------------------------------------- editors


def _editor_rows(db: Session, start: datetime, end: datetime, gran: str, person_ids=None) -> list[dict]:
    links = select(ItemPerson.item_id, ItemPerson.person_id)
    if person_ids is not None:
        links = links.where(ItemPerson.person_id.in_(list(person_ids)))
    pairs = db.execute(links).all()
    by_person: dict[int, set[int]] = defaultdict(set)
    for item_id, pid in pairs:
        by_person[pid].add(item_id)
    all_items = {i for s in by_person.values() for i in s}
    totals = _totals(db, start, end, gran, all_items)
    published = {
        i.id
        for i in db.execute(
            select(ContentItem).where(
                ContentItem.id.in_(list(all_items)), ContentItem.published_at >= start, ContentItem.published_at < end
            )
        ).scalars()
    }
    people = {p.id: p for p in db.execute(select(Person).where(Person.id.in_(list(by_person)))).scalars()}
    # Social posts and videos that link to the editors' articles.
    social_of: dict[int, set[int]] = defaultdict(set)
    for from_id, to_id in db.execute(
        select(ItemLink.from_item_id, ItemLink.to_item_id).where(ItemLink.to_item_id.in_(list(all_items)))
    ).all():
        social_of[to_id].add(from_id)
    social_ids = {i for s in social_of.values() for i in s}
    social_totals = _totals(db, start, end, gran, social_ids)
    social_kind = dict(
        db.execute(
            select(ContentItem.id, Source.kind)
            .join(Source, Source.id == ContentItem.source_id)
            .where(ContentItem.id.in_(list(social_ids)))
        ).all()
    )
    rows = []
    for pid, item_ids in by_person.items():
        p = people.get(pid)
        if p is None:
            continue
        sums: dict[str, float] = defaultdict(float)
        for i in item_ids:
            for k, v in totals.get(i, {}).items():
                if k != "peak":
                    sums[k] += v
        views = sums.get("views", 0)
        rows.append(
            {
                "id": p.id,
                "name": p.display_name,
                "linked_user": p.user_id is not None,
                "items": len(item_ids),
                "published": len(item_ids & published),
                "metrics": {k: round(sums.get(k, 0), 2) for k in TOTALS if k != "peak"},
                "avg_read_seconds": round(sums.get("read_seconds", 0) / views, 1) if views else 0,
                "social": _social_sums({s for i in item_ids for s in social_of.get(i, ())}, social_totals, social_kind),
            }
        )
    rows.sort(key=lambda r: -r["metrics"]["views"])
    return rows


SOCIAL_KEYS = ("views", "reach", "likes", "comments", "shares")


def _social_sums(ids: set[int], totals: dict[int, dict], kinds: dict[int, str]) -> dict:
    """Totals over linked posts and videos, overall and per platform."""
    out: dict = {"posts": len(ids), **dict.fromkeys(SOCIAL_KEYS, 0.0), "by_kind": {}}
    for i in ids:
        kind = kinds.get(i, "other")
        per = out["by_kind"].setdefault(kind, {"posts": 0, **dict.fromkeys(SOCIAL_KEYS, 0.0)})
        per["posts"] += 1
        for k in SOCIAL_KEYS:
            v = totals.get(i, {}).get(k, 0)
            out[k] += v
            per[k] += v
    for d in (out, *out["by_kind"].values()):
        for k in SOCIAL_KEYS:
            d[k] = round(d[k], 2)
    return out


@router.get("/editors")
def editors(range: Range = "30d", db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    start, end, gran, _ = period(db, range)
    if user.role in SEES_ALL:
        rows = _editor_rows(db, start, end, gran)
        scope = "all"
    elif user.role == "editor":
        me = own_person(db, user)
        rows = _editor_rows(db, start, end, gran, [me.id]) if me else []
        scope = "own"
    else:
        raise HTTPException(403, "forbidden")
    return {"range": range, "scope": scope, "start": start.isoformat(), "end": end.isoformat(), "editors": rows}


@router.get("/editors/{person_id}")
def editor_detail(
    person_id: int, range: Range = "30d", db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    _check_person_access(db, user, person_id)
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(404, "not_found")
    start, end, gran, buckets = period(db, range)
    rows = _editor_rows(db, start, end, gran, [person_id])
    item_ids = select(ItemPerson.item_id).where(ItemPerson.person_id == person_id)
    return {
        "range": range,
        "granularity": gran,
        "buckets": [b.isoformat() for b in buckets],
        "editor": rows[0] if rows else {"id": person.id, "name": person.display_name, "items": 0},
        "series": _series(db, gran, buckets, [MetricPoint.item_id.in_(item_ids)]),
    }
