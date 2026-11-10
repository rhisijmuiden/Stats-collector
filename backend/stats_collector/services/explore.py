"""Series for dashboard widgets: one canonical measure over a period, per source, per platform or in total.

Measures use the canonical categories (see services/goals.GOAL_METRICS), so channels can be stacked
into one total: reach, views, interactions, watch/listen minutes and followers. Followers is a count
per day (carried forward over days without a number); the others are sums per bucket.

YouTube, Facebook and Instagram only report whole days, so a 24-hour period has no hourly numbers for
them; their series is empty there and marked `daily_only`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import MetricPoint, Source
from .goals import GOAL_METRICS

MEASURES = tuple(GOAL_METRICS)
LEVEL = ("followers",)
DAILY_ONLY = ("youtube", "facebook", "instagram")
PLATFORM = {"wordpress": "website"}  # source kind → platform (channel colour) name; others are the same


def platform(kind: str) -> str:
    return PLATFORM.get(kind, kind)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def sources_for(db: Session, measure: str, source_ids: list[int] | None, platforms: list[str] | None) -> list[Source]:
    """Sources that report this measure, narrowed to the chosen ids and platforms."""
    metrics = GOAL_METRICS[measure]
    stmt = select(Source).order_by(Source.kind, Source.name)
    if source_ids:
        stmt = stmt.where(Source.id.in_(source_ids))
    out = []
    reporting = set(
        db.execute(select(MetricPoint.source_id).where(MetricPoint.metric.in_(metrics)).distinct()).scalars()
    )
    for s in db.execute(stmt).scalars():
        if platforms and platform(s.kind) not in platforms:
            continue
        if s.id in reporting:
            out.append(s)
    return out


def per_source(
    db: Session, measure: str, sources: list[Source], start: datetime, end: datetime, gran: str, buckets: list[datetime]
) -> dict[int, list[float | None]]:
    """Values per bucket for each source."""
    index = {b: i for i, b in enumerate(buckets)}
    level = measure in LEVEL
    out: dict[int, list[float | None]] = {s.id: [None] * len(buckets) for s in sources}
    if not sources:
        return out
    ids = [s.id for s in sources]
    base = [
        MetricPoint.source_id.in_(ids),
        MetricPoint.item_id.is_(None),
        MetricPoint.granularity == gran,
        MetricPoint.metric.in_(GOAL_METRICS[measure]),
    ]
    rows = db.execute(
        select(MetricPoint.source_id, MetricPoint.bucket, func.sum(MetricPoint.value))
        .where(*base, MetricPoint.bucket >= start, MetricPoint.bucket < end)
        .group_by(MetricPoint.source_id, MetricPoint.bucket)
    ).all()
    for source_id, bucket, value in rows:
        i = index.get(_aware(bucket))
        if i is not None:
            out[source_id][i] = round(float(value or 0), 2)
    if level:
        # A count: start from the last known number before the period and carry it over gaps.
        for sid, values in out.items():
            last = db.execute(
                select(MetricPoint.value)
                .where(*base, MetricPoint.source_id == sid, MetricPoint.bucket < start)
                .order_by(MetricPoint.bucket.desc())
                .limit(1)
            ).scalar_one_or_none()
            for i, v in enumerate(values):
                if v is None:
                    values[i] = last
                else:
                    last = v
    else:
        daily_only = {s.id for s in sources if s.kind in DAILY_ONLY}
        for sid, values in out.items():
            if gran == "day" or sid not in daily_only:
                out[sid] = [0.0 if v is None else v for v in values]
    return out


def total(values: list[float | None], level: bool) -> float:
    """A series' total: the sum, or for a count its last known value."""
    if level:
        known = [v for v in values if v is not None]
        return known[-1] if known else 0.0
    return round(sum(v or 0 for v in values), 2)


def group(sources: list[Source], values: dict[int, list[float | None]], split: str) -> list[dict]:
    """Series per source, per platform or one total."""
    if split == "source":
        return [
            {"key": str(s.id), "name": s.name, "kind": s.kind, "platform": platform(s.kind), "values": values[s.id]}
            for s in sources
        ]
    groups: dict[str, list[Source]] = defaultdict(list)
    for s in sources:
        groups[platform(s.kind) if split == "platform" else "total"].append(s)
    out = []
    for key, members in groups.items():
        cols = zip(*[values[s.id] for s in members], strict=True)
        merged = [None if all(v is None for v in col) else round(sum(v or 0 for v in col), 2) for col in cols]
        out.append({"key": key, "name": key, "kind": members[0].kind, "platform": key, "values": merged})
    return out
