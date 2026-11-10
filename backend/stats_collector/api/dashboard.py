"""Dashboard data: live audience now, time series and totals per source."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..connectors import STREAM_KINDS
from ..db import get_db
from ..models import ContentItem, MetricPoint, Source, StreamSample, User, utcnow
from ..security import current_user
from ..services.metrics import LIVE_MINUTES, LIVE_PEAK
from ..services.rollup import local_day_start, next_local_day, org_timezone

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

Range = Literal["24h", "7d", "30d", "90d", "365d"]
Metric = Literal["live_avg", "live_peak", "live_minutes"]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _sources(db: Session) -> list[Source]:
    return list(
        db.execute(select(Source).where(Source.kind.in_(STREAM_KINDS)).order_by(Source.kind, Source.name)).scalars()
    )


def _source_brief(s: Source) -> dict:
    return {"id": s.id, "name": s.name, "kind": s.kind, "enabled": s.enabled}


@router.get("/live")
def live(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    now = utcnow()
    tz = org_timezone(db)
    today = local_day_start(now, tz)
    out = []
    total = 0.0
    for s in _sources(db):
        window = now - timedelta(seconds=max(120, 3 * s.poll_seconds))
        last_ts = db.execute(
            select(func.max(StreamSample.ts)).where(StreamSample.source_id == s.id, StreamSample.ts >= window)
        ).scalar_one()
        items: list[dict] = []
        audience = 0.0
        online = False
        if last_ts is not None:
            rows = db.execute(
                select(StreamSample, ContentItem)
                .outerjoin(ContentItem, ContentItem.id == StreamSample.item_id)
                .where(StreamSample.source_id == s.id, StreamSample.ts == last_ts)
            ).all()
            for sample, item in rows:
                audience += sample.value
                online = online or sample.online
                if item is not None:
                    items.append(
                        {
                            "id": item.id,
                            "title": item.title,
                            "kind": item.kind,
                            "value": sample.value,
                            "online": sample.online,
                            "now_playing": (sample.extra or {}).get("now_playing"),
                        }
                    )
        peak_today = db.execute(
            select(func.max(MetricPoint.value)).where(
                MetricPoint.source_id == s.id,
                MetricPoint.item_id.is_(None),
                MetricPoint.metric == LIVE_PEAK,
                MetricPoint.granularity == "hour",
                MetricPoint.bucket >= today,
            )
        ).scalar_one()
        minutes_today = db.execute(
            select(func.sum(MetricPoint.value)).where(
                MetricPoint.source_id == s.id,
                MetricPoint.item_id.is_(None),
                MetricPoint.metric == LIVE_MINUTES,
                MetricPoint.granularity == "hour",
                MetricPoint.bucket >= today,
            )
        ).scalar_one()
        total += audience
        out.append(
            {
                **_source_brief(s),
                "online": online,
                "audience": audience,
                "items": items,
                "peak_today": max(peak_today or 0, audience),
                "minutes_today": round(minutes_today or 0, 1),
                "stale": last_ts is None and s.enabled,
                "last_error": s.last_error,
                "updated_at": _aware(last_ts).isoformat() if last_ts else None,
            }
        )
    return {"at": now.isoformat(), "total": total, "sources": out}


def _range(r: str, now: datetime, db: Session) -> tuple[datetime, datetime, str, timedelta | None]:
    if r == "24h":
        step = timedelta(minutes=5)
        end = now.replace(second=0, microsecond=0)
        end = end - timedelta(minutes=end.minute % 5) + step
        return end - timedelta(hours=24), end, "5min", step
    if r == "7d":
        end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return end - timedelta(days=7), end, "hour", timedelta(hours=1)
    days = int(r.rstrip("d"))
    tz = org_timezone(db)
    end = next_local_day(local_day_start(now, tz), tz)
    start = local_day_start(end - timedelta(days=days, hours=-12), tz)
    return start, end, "day", None


def _day_buckets(start: datetime, end: datetime, db: Session) -> list[datetime]:
    tz = org_timezone(db)
    out, day = [], start
    while day < end:
        out.append(day)
        day = next_local_day(day, tz)
    return out


@router.get("/series")
def series(
    range: Range = "24h", metric: Metric = "live_avg", db: Session = Depends(get_db), _: User = Depends(current_user)
) -> dict:
    now = utcnow()
    start, end, granularity, step = _range(range, now, db)
    if step is not None:
        buckets = []
        b = start
        while b < end:
            buckets.append(b)
            b += step
    else:
        buckets = _day_buckets(start, end, db)
    index = {b: i for i, b in enumerate(buckets)}
    out = []
    for s in _sources(db):
        values: list[float | None] = [None] * len(buckets)
        if granularity == "5min":
            # Straight from the raw samples: per poll the sum over mounts, then per 5 minutes.
            rows = db.execute(
                select(StreamSample.ts, func.sum(StreamSample.value))
                .where(StreamSample.source_id == s.id, StreamSample.ts >= start, StreamSample.ts < end)
                .group_by(StreamSample.ts)
            ).all()
            acc: dict[int, list[float]] = defaultdict(list)
            for ts, value in rows:
                ts = _aware(ts)
                i = int((ts - start).total_seconds() // 300)
                if 0 <= i < len(buckets):
                    acc[i].append(float(value or 0))
            for i, vals in acc.items():
                if metric == LIVE_PEAK:
                    values[i] = max(vals)
                elif metric == LIVE_MINUTES:
                    values[i] = round(sum(vals) / len(vals) * 5, 2)
                else:
                    values[i] = round(sum(vals) / len(vals), 2)
        else:
            rows = db.execute(
                select(MetricPoint.bucket, MetricPoint.value).where(
                    MetricPoint.source_id == s.id,
                    MetricPoint.item_id.is_(None),
                    MetricPoint.metric == metric,
                    MetricPoint.granularity == granularity,
                    MetricPoint.bucket >= start,
                    MetricPoint.bucket < end,
                )
            ).all()
            for bucket, value in rows:
                i = index.get(_aware(bucket))
                if i is not None:
                    values[i] = value
        out.append({**_source_brief(s), "values": values})
    return {
        "range": range,
        "metric": metric,
        "granularity": granularity,
        "buckets": [b.isoformat() for b in buckets],
        "series": out,
    }


@router.get("/summary")
def summary(range: Range = "7d", db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    now = utcnow()
    start, end, _g, _s = _range(range, now, db)
    rows = db.execute(
        select(
            MetricPoint.source_id,
            MetricPoint.item_id,
            MetricPoint.metric,
            func.sum(MetricPoint.value),
            func.max(MetricPoint.value),
        )
        .where(
            MetricPoint.granularity == "hour",
            MetricPoint.bucket >= start,
            MetricPoint.bucket < end,
            MetricPoint.metric.in_((LIVE_MINUTES, LIVE_PEAK)),
        )
        .group_by(MetricPoint.source_id, MetricPoint.item_id, MetricPoint.metric)
    ).all()
    per_source: dict[int, dict] = defaultdict(lambda: {"minutes": 0.0, "peak": 0.0})
    per_item: dict[int, dict] = defaultdict(lambda: {"minutes": 0.0, "peak": 0.0})
    for source_id, item_id, metric, total, peak in rows:
        target = per_source[source_id] if item_id is None else per_item[item_id]
        if metric == LIVE_MINUTES:
            target["minutes"] = round(total or 0, 1)
        else:
            target["peak"] = peak or 0
    hours = (end - start).total_seconds() / 3600
    sources = []
    for s in _sources(db):
        v = per_source.get(s.id, {"minutes": 0.0, "peak": 0.0})
        sources.append({**_source_brief(s), **v, "avg": round(v["minutes"] / (hours * 60), 2) if hours else 0})
    top = []
    if per_item:
        items = {i.id: i for i in db.execute(select(ContentItem).where(ContentItem.id.in_(per_item))).scalars()}
        by_id = {s.id: s for s in _sources(db)}
        for item_id, v in sorted(per_item.items(), key=lambda kv: -kv[1]["minutes"])[:10]:
            item = items.get(item_id)
            if item is None:
                continue
            top.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "kind": item.kind,
                    "source": by_id[item.source_id].name if item.source_id in by_id else None,
                    "source_kind": by_id[item.source_id].kind if item.source_id in by_id else None,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "ended_at": item.ended_at.isoformat() if item.ended_at else None,
                    **v,
                }
            )
    return {
        "range": range,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_minutes": round(sum(s["minutes"] for s in sources), 1),
        "peak": max((s["peak"] for s in sources), default=0),
        "sources": sources,
        "top_items": top,
    }


# ----------------------------------------------------------------------------- website and video

CHANNEL_KINDS = ("wordpress", "youtube", "facebook", "instagram")
VIEW_METRICS = {"wordpress": "web_views", "youtube": "yt_views", "facebook": "fb_views", "instagram": "ig_views"}
REACH_METRICS = {"wordpress": "web_visitors", "facebook": "fb_reach", "instagram": "ig_reach"}
GAINED_METRICS = {"youtube": "yt_subs_gained", "facebook": "fb_follows", "instagram": "ig_follows"}
DAILY_ONLY = ("youtube", "facebook", "instagram")
FOLLOWER_CONFIG = {"youtube": "subscribers", "facebook": "followers", "instagram": "followers"}


@router.get("/channels")
def channels(range: Range = "7d", db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    """Views per website, YouTube channel, Facebook Page and Instagram account, with a series per
    hour (24 h) or day. Reach is unique visitors for a website and Meta's reach for social media;
    summed over days it counts a person once per day."""
    from .content import period

    start, end, gran, buckets = period(db, range)
    index = {b: i for i, b in enumerate(buckets)}
    sources = list(
        db.execute(select(Source).where(Source.kind.in_(CHANNEL_KINDS)).order_by(Source.kind, Source.name)).scalars()
    )
    out = []
    for s in sources:
        views_metric = VIEW_METRICS[s.kind]
        wanted = {views_metric, "yt_watch_minutes", REACH_METRICS.get(s.kind), GAINED_METRICS.get(s.kind)} - {None}
        totals = dict(
            db.execute(
                select(MetricPoint.metric, func.sum(MetricPoint.value))
                .where(
                    MetricPoint.source_id == s.id,
                    MetricPoint.item_id.is_(None),
                    MetricPoint.granularity == gran,
                    MetricPoint.bucket >= start,
                    MetricPoint.bucket < end,
                    MetricPoint.metric.in_(tuple(wanted)),
                )
                .group_by(MetricPoint.metric)
            ).all()
        )
        values: list[float | None] = [None] * len(buckets)
        for bucket, value in db.execute(
            select(MetricPoint.bucket, MetricPoint.value).where(
                MetricPoint.source_id == s.id,
                MetricPoint.item_id.is_(None),
                MetricPoint.granularity == gran,
                MetricPoint.metric == views_metric,
                MetricPoint.bucket >= start,
                MetricPoint.bucket < end,
            )
        ).all():
            i = index.get(_aware(bucket))
            if i is not None:
                values[i] = value
        out.append(
            {
                **_source_brief(s),
                # YouTube and Meta only report whole days: no numbers per hour.
                "daily_only": s.kind in DAILY_ONLY,
                "views": round(totals.get(views_metric) or 0),
                "visitors": round(totals.get("web_visitors") or 0),
                "reach": round(totals.get(REACH_METRICS.get(s.kind, ""), 0) or 0),
                "watch_minutes": round(totals.get("yt_watch_minutes") or 0),
                "subscribers": (s.config or {}).get(FOLLOWER_CONFIG[s.kind]) if s.kind in FOLLOWER_CONFIG else None,
                "subscribers_gained": round(totals.get(GAINED_METRICS.get(s.kind, ""), 0) or 0),
                "values": values,
                "last_ok_at": _aware(s.last_ok_at).isoformat() if s.last_ok_at else None,
            }
        )
    return {
        "range": range,
        "granularity": gran,
        "buckets": [b.isoformat() for b in buckets],
        "total_views": sum(s["views"] for s in out),
        "total_reach": sum(s["reach"] for s in out),
        "sources": out,
    }
