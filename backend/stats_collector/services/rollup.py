"""Turns raw stream samples into hourly, daily and monthly metric points.

Hour buckets are UTC hours. Day and month buckets follow the organisation's time zone
(Settings → General), stored as the UTC instant of local midnight.

Per bucket and per source (and per item):
  live_minutes  sum of audience x time between polls (a gap longer than two poll intervals
                counts as one interval, so an outage of the collector is not filled in)
  live_avg      live_minutes spread over the whole bucket (offline time counts as zero)
  live_peak     highest audience seen in one poll
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import MetricPoint, Source, StreamSample, utcnow
from . import settings_store
from .metrics import LIVE_AVG, LIVE_MINUTES, LIVE_PEAK

RAW_RETENTION_DAYS = 365


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def org_timezone(db: Session) -> ZoneInfo:
    name = settings_store.get_section(db, "general").get("timezone") or "Europe/Amsterdam"
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - unknown zone name in settings
        return ZoneInfo("Europe/Amsterdam")


def hour_floor(dt: datetime) -> datetime:
    return _aware(dt).astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def local_day_start(dt: datetime, tz: ZoneInfo) -> datetime:
    local = _aware(dt).astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def local_month_start(dt: datetime, tz: ZoneInfo) -> datetime:
    local = _aware(dt).astimezone(tz)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def next_local_day(start: datetime, tz: ZoneInfo) -> datetime:
    local = start.astimezone(tz)
    return (local + timedelta(days=1, hours=3)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def next_local_month(start: datetime, tz: ZoneInfo) -> datetime:
    local = start.astimezone(tz)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return local.replace(year=year, month=month, day=1).astimezone(UTC)


def summarise(points: list[tuple[datetime, float]], start: datetime, end: datetime, poll_s: int) -> dict:
    """points: (ts, value) sorted by ts, all within [start, end)."""
    minutes = 0.0
    peak = 0.0
    max_gap = 2 * poll_s
    for i, (ts, value) in enumerate(points):
        nxt = points[i + 1][0] if i + 1 < len(points) else min(end, ts + timedelta(seconds=poll_s))
        dt = (nxt - ts).total_seconds()
        if dt > max_gap:  # collector was down: count one interval, do not fill the gap
            dt = poll_s
        minutes += value * max(dt, 0) / 60
        peak = max(peak, value)
    span_min = (end - start).total_seconds() / 60
    return {LIVE_MINUTES: round(minutes, 2), LIVE_PEAK: peak, LIVE_AVG: round(minutes / span_min, 3) if span_min else 0}


def _replace_points(db: Session, source: Source, granularity: str, bucket: datetime,
                    values: dict[int | None, dict[str, float]]) -> None:
    db.execute(
        delete(MetricPoint).where(
            MetricPoint.source_id == source.id, MetricPoint.granularity == granularity, MetricPoint.bucket == bucket
        )
    )
    for item_id, metrics in values.items():
        for metric, value in metrics.items():
            db.add(MetricPoint(tenant_id=source.tenant_id, source_id=source.id, item_id=item_id, metric=metric,
                               granularity=granularity, bucket=bucket, value=value))


def rollup_hour(db: Session, source: Source, hour: datetime) -> None:
    start = hour_floor(hour)
    end = start + timedelta(hours=1)
    rows = db.execute(
        select(StreamSample.ts, StreamSample.item_id, StreamSample.value)
        .where(StreamSample.source_id == source.id, StreamSample.ts >= start, StreamSample.ts < end)
        .order_by(StreamSample.ts)
    ).all()
    if not rows:
        return
    totals: dict[datetime, float] = defaultdict(float)
    per_item: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for ts, item_id, value in rows:
        ts = _aware(ts)
        totals[ts] += value
        if item_id is not None:
            per_item[item_id].append((ts, value))
    poll_s = max(10, source.poll_seconds)
    values: dict[int | None, dict[str, float]] = {None: summarise(sorted(totals.items()), start, end, poll_s)}
    for item_id, pts in per_item.items():
        if any(v for _, v in pts):
            values[item_id] = summarise(pts, start, end, poll_s)
    _replace_points(db, source, "hour", start, values)


def _rollup_from(db: Session, source: Source, src_gran: str, dst_gran: str, start: datetime, end: datetime) -> None:
    rows = db.execute(
        select(MetricPoint.item_id, MetricPoint.metric, MetricPoint.value).where(
            MetricPoint.source_id == source.id,
            MetricPoint.granularity == src_gran,
            MetricPoint.bucket >= start,
            MetricPoint.bucket < end,
        )
    ).all()
    if not rows:
        return
    acc: dict[int | None, dict[str, float]] = defaultdict(lambda: {LIVE_MINUTES: 0.0, LIVE_PEAK: 0.0})
    for item_id, metric, value in rows:
        if metric == LIVE_MINUTES:
            acc[item_id][LIVE_MINUTES] += value
        elif metric == LIVE_PEAK:
            acc[item_id][LIVE_PEAK] = max(acc[item_id][LIVE_PEAK], value)
    span_min = (end - start).total_seconds() / 60
    for metrics in acc.values():
        metrics[LIVE_MINUTES] = round(metrics[LIVE_MINUTES], 2)
        metrics[LIVE_AVG] = round(metrics[LIVE_MINUTES] / span_min, 3)
    _replace_points(db, source, dst_gran, start, dict(acc))


def rollup(db: Session, since: datetime | None = None, now: datetime | None = None) -> int:
    """Recompute buckets from `since` (default: two hours ago) up to now. Returns hours processed."""
    now = _aware(now or utcnow())
    since = hour_floor(since or now - timedelta(hours=2))
    tz = org_timezone(db)
    sources = list(db.execute(select(Source).where(Source.kind.in_(("icecast", "owncast")))).scalars())
    hours = 0
    for source in sources:
        hour = since
        while hour <= now:
            rollup_hour(db, source, hour)
            hour += timedelta(hours=1)
            hours += 1
        day = local_day_start(since, tz)
        while day <= now:
            _rollup_from(db, source, "hour", "day", day, next_local_day(day, tz))
            day = next_local_day(day, tz)
        month = local_month_start(since, tz)
        while month <= now:
            _rollup_from(db, source, "day", "month", month, next_local_month(month, tz))
            month = next_local_month(month, tz)
        db.commit()
    return hours


def prune_samples(db: Session, now: datetime | None = None) -> int:
    cutoff = _aware(now or utcnow()) - timedelta(days=RAW_RETENTION_DAYS)
    result = db.execute(delete(StreamSample).where(StreamSample.ts < cutoff))
    db.commit()
    return result.rowcount or 0
