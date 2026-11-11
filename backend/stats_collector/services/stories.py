"""Stories: one subject followed over website, radio, live streams and social media.

A story is made of
  - items picked by hand (articles, posts, videos, broadcasts);
  - every post or video linked to one of those articles, and the article a picked post links to
    (the same links as under Content);
  - items whose title contains one of the story's keywords, published within the story's dates;
  - radio slots: a stream source with a start and end time (e.g. the interview on air), measured
    from the listener counts of that time;
minus items that were removed from the story by hand.

The numbers cover the story's dates (to today when it has no end date).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import ContentItem, ItemLink, ItemPerson, MetricPoint, Person, Source, Story, StreamSample, utcnow
from .measures import INTERACTIONS, VIEWS, aware
from .metrics import LIVE_MINUTES, LIVE_PEAK
from .rollup import local_day_start, next_local_day, org_timezone

MAX_KEYWORD_ITEMS = 200


def platform(kind: str) -> str:
    return "website" if kind == "wordpress" else kind


def window(db: Session, story: Story, now: datetime | None = None) -> tuple[datetime, datetime, list[datetime]]:
    """Local days from the start date to the end date (or today)."""
    now = now or utcnow()
    tz = org_timezone(db)
    today = now.astimezone(tz).date()
    last = min(story.end_date, today) if story.end_date else today
    last = max(last, story.start_date)
    days, day = [], local_day_start(datetime.combine(story.start_date, datetime.min.time(), tz), tz)
    end = next_local_day(local_day_start(datetime.combine(last, datetime.min.time(), tz), tz), tz)
    while day < end:
        days.append(day)
        day = next_local_day(day, tz)
    return days[0], end, days


def resolve(db: Session, story: Story, start: datetime, end: datetime) -> dict[int, str]:
    """{item id: why it is in the story} — "picked", "linked" or "keyword"."""
    excluded = {int(i) for i in story.excluded_ids or []}
    out: dict[int, str] = {}
    picked = [int(i) for i in story.item_ids or []]
    for i in picked:
        out[i] = "picked"
    if picked:
        for a, b in db.execute(
            select(ItemLink.from_item_id, ItemLink.to_item_id).where(
                or_(ItemLink.from_item_id.in_(picked), ItemLink.to_item_id.in_(picked))
            )
        ).all():
            for i in (a, b):
                out.setdefault(i, "linked")
    words = [w.strip() for w in story.keywords or [] if w and w.strip()]
    if words:
        rows = db.execute(
            select(ContentItem.id)
            .where(
                or_(*[ContentItem.title.ilike(f"%{w}%") for w in words]),
                ContentItem.published_at >= start - timedelta(days=1),
                ContentItem.published_at < end,
            )
            .limit(MAX_KEYWORD_ITEMS)
        ).scalars()
        for i in rows:
            out.setdefault(i, "keyword")
    return {i: why for i, why in out.items() if i not in excluded}


def radio_slot(db: Session, slot: dict, sources: dict[int, Source]) -> dict | None:
    source = sources.get(int(slot.get("source_id") or 0))
    try:
        start = aware(datetime.fromisoformat(slot["start"]))
        end = aware(datetime.fromisoformat(slot["end"]))
    except (KeyError, TypeError, ValueError):
        return None
    if source is None or end <= start:
        return None
    rows = db.execute(
        select(StreamSample.ts, func.sum(StreamSample.value))
        .where(StreamSample.source_id == source.id, StreamSample.ts >= start, StreamSample.ts < end)
        .group_by(StreamSample.ts)
        .order_by(StreamSample.ts)
    ).all()
    values = [float(v or 0) for _, v in rows]
    avg = sum(values) / len(values) if values else 0.0
    minutes = (end - start).total_seconds() / 60
    return {
        "source": {"id": source.id, "name": source.name, "kind": source.kind},
        "label": slot.get("label") or "",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "avg": round(avg, 1),
        "peak": round(max(values), 1) if values else 0,
        "listener_minutes": round(avg * minutes),
        "samples": len(values),
    }


def detail(db: Session, story: Story, now: datetime | None = None, authors: bool = True) -> dict:
    start, end, days = window(db, story, now)
    reasons = resolve(db, story, start, end)
    items = {i.id: i for i in db.execute(select(ContentItem).where(ContentItem.id.in_(list(reasons)))).scalars()}
    sources = {s.id: s for s in db.execute(select(Source)).scalars()}
    index = {d: n for n, d in enumerate(days)}

    per_item: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    series: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"views": [0.0] * len(days), "interactions": [0.0] * len(days)}
    )
    if items:
        for item_id, metric, bucket, value in db.execute(
            select(MetricPoint.item_id, MetricPoint.metric, MetricPoint.bucket, MetricPoint.value).where(
                MetricPoint.item_id.in_(list(items)),
                MetricPoint.granularity == "day",
                MetricPoint.metric.in_((*VIEWS, *INTERACTIONS, LIVE_MINUTES, LIVE_PEAK)),
                MetricPoint.bucket >= start,
                MetricPoint.bucket < end,
            )
        ).all():
            v = float(value or 0)
            item = items[item_id]
            plat = platform(sources[item.source_id].kind) if item.source_id in sources else "other"
            n = index.get(aware(bucket))
            if metric in VIEWS:
                per_item[item_id]["views"] += v
                if n is not None:
                    series[plat]["views"][n] += v
            elif metric in INTERACTIONS:
                per_item[item_id]["interactions"] += v
                if n is not None:
                    series[plat]["interactions"][n] += v
            elif metric == LIVE_MINUTES:
                per_item[item_id]["listener_minutes"] += v
            elif metric == LIVE_PEAK:
                per_item[item_id]["peak"] = max(per_item[item_id]["peak"], v)

    names: dict[int, list[str]] = defaultdict(list)
    if authors and items:
        for item_id, name in db.execute(
            select(ItemPerson.item_id, Person.display_name)
            .join(Person, Person.id == ItemPerson.person_id)
            .where(ItemPerson.item_id.in_(list(items)))
        ).all():
            names[item_id].append(name)

    channels: dict[str, dict] = {}
    rows = []
    for item_id, item in items.items():
        s = sources.get(item.source_id)
        plat = platform(s.kind) if s else "other"
        m = per_item.get(item_id, {})
        c = channels.setdefault(
            plat,
            {"platform": plat, "items": 0, "views": 0.0, "interactions": 0.0, "listener_minutes": 0.0, "peak": 0.0},
        )
        c["items"] += 1
        c["views"] += m.get("views", 0)
        c["interactions"] += m.get("interactions", 0)
        c["listener_minutes"] += m.get("listener_minutes", 0)
        c["peak"] = max(c["peak"], m.get("peak", 0))
        rows.append(
            {
                "id": item.id,
                "title": item.title,
                "kind": item.kind,
                "url": item.url,
                "source": {"id": s.id, "name": s.name, "kind": s.kind} if s else None,
                "published_at": aware(item.published_at).isoformat() if item.published_at else None,
                "why": reasons[item_id],
                "views": round(m.get("views", 0)),
                "interactions": round(m.get("interactions", 0)),
                "listener_minutes": round(m.get("listener_minutes", 0)),
                "peak": round(m.get("peak", 0)),
                "authors": names.get(item_id, []) if authors else [],
            }
        )
    rows.sort(key=lambda r: (-r["views"], -r["interactions"]))

    radio = [r for r in (radio_slot(db, s, sources) for s in story.radio or []) if r]
    for r in radio:
        plat = platform(r["source"]["kind"])
        c = channels.setdefault(
            plat,
            {"platform": plat, "items": 0, "views": 0.0, "interactions": 0.0, "listener_minutes": 0.0, "peak": 0.0},
        )
        c["items"] += 1
        c["listener_minutes"] += r["listener_minutes"]
        c["peak"] = max(c["peak"], r["peak"])
    for c in channels.values():
        for k in ("views", "interactions", "listener_minutes", "peak"):
            c[k] = round(c[k])
    totals = {
        "items": len(rows) + len(radio),
        "channels": len(channels),
        "views": sum(c["views"] for c in channels.values()),
        "interactions": sum(c["interactions"] for c in channels.values()),
        "listener_minutes": sum(c["listener_minutes"] for c in channels.values()),
    }
    return {
        **summary(story),
        "days": [d.isoformat() for d in days],
        "totals": totals,
        "channels": sorted(channels.values(), key=lambda c: -(c["views"] + c["interactions"] + c["listener_minutes"])),
        "series": {p: {k: [round(v) for v in vs] for k, vs in s.items()} for p, s in series.items()},
        "items": rows,
        "radio": radio,
    }


def summary(story: Story) -> dict:
    return {
        "id": story.id,
        "name": story.name,
        "description": story.description or "",
        "item_ids": [int(i) for i in story.item_ids or []],
        "excluded_ids": [int(i) for i in story.excluded_ids or []],
        "keywords": list(story.keywords or []),
        "radio": list(story.radio or []),
        "start_date": story.start_date.isoformat(),
        "end_date": story.end_date.isoformat() if story.end_date else None,
        "updated_at": aware(story.updated_at).isoformat() if story.updated_at else None,
    }


def card(db: Session, story: Story, now: datetime | None = None) -> dict:
    """The list view: totals and channels only."""
    d = detail(db, story, now, authors=False)
    return {k: v for k, v in d.items() if k not in ("items", "series", "radio", "days")}
