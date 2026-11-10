"""Follower and subscriber counts per day, for platforms that only report today's count.

YouTube, Facebook and Instagram give the current number of followers, and per day how many
followed and (except Instagram) unfollowed. The count of each earlier day is worked back from a
known count with those daily changes. Counts that were really seen (one per sync, kept in the
source's config as `follower_log`) are used as fixed points, so the history stays exact once the
app has been running for a while.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import MetricPoint, Source
from .rollup import local_month_start, next_local_month

LOG_DAYS = 800  # how many daily counts are kept in config["follower_log"]


def day_bucket(day: date, tz) -> datetime:
    return datetime.combine(day, dtime(0), tz).astimezone(UTC)


def log_count(cfg: dict, today: date, count: int) -> dict[date, int]:
    """Remember today's count in the config and return all remembered counts."""
    log = dict(cfg.get("follower_log") or {})
    log[today.isoformat()] = int(count)
    keep = sorted(log)[-LOG_DAYS:]
    cfg["follower_log"] = {k: log[k] for k in keep}
    return {date.fromisoformat(k): v for k, v in cfg["follower_log"].items()}


def rebuild_gauge(
    db: Session,
    source: Source,
    gauge: str,
    gained: str,
    lost: str | None,
    anchors: dict[date, int],
    today: date,
    tz,
) -> None:
    """Write `gauge` per day (and per month: its last day) from known counts and daily changes."""
    metrics = (gained, lost) if lost else (gained,)
    rows = db.execute(
        select(MetricPoint.bucket, MetricPoint.metric, MetricPoint.value).where(
            MetricPoint.source_id == source.id,
            MetricPoint.item_id.is_(None),
            MetricPoint.granularity == "day",
            MetricPoint.metric.in_(metrics),
        )
    ).all()
    net: dict[date, float] = {}
    for bucket, metric, value in rows:
        b = bucket if bucket.tzinfo else bucket.replace(tzinfo=UTC)
        day = b.astimezone(tz).date()
        net[day] = net.get(day, 0) + (value if metric == gained else -value)
    db.execute(
        delete(MetricPoint).where(
            MetricPoint.source_id == source.id,
            MetricPoint.item_id.is_(None),
            MetricPoint.metric == gauge,
        )
    )
    if today not in anchors:
        return
    first = min([*net, *anchors])
    count = float(anchors[today])
    day = today
    while day >= first:
        if day in anchors:
            count = float(anchors[day])
        db.add(
            MetricPoint(
                tenant_id=source.tenant_id,
                source_id=source.id,
                item_id=None,
                metric=gauge,
                granularity="day",
                bucket=day_bucket(day, tz),
                value=max(count, 0),
            )
        )
        count -= net.get(day, 0)  # count at the end of the previous day
        day -= timedelta(days=1)
    db.flush()
    month = local_month_start(day_bucket(first, tz), tz)
    end = day_bucket(today, tz)
    while month <= end:
        nxt = next_local_month(month, tz)
        last = db.execute(
            select(MetricPoint.value)
            .where(
                MetricPoint.source_id == source.id,
                MetricPoint.item_id.is_(None),
                MetricPoint.metric == gauge,
                MetricPoint.granularity == "day",
                MetricPoint.bucket >= month,
                MetricPoint.bucket < nxt,
            )
            .order_by(MetricPoint.bucket.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last is not None:
            db.add(
                MetricPoint(
                    tenant_id=source.tenant_id,
                    source_id=source.id,
                    item_id=None,
                    metric=gauge,
                    granularity="month",
                    bucket=month,
                    value=last,
                )
            )
        month = nxt
