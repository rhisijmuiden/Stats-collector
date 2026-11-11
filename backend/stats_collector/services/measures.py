"""Shared helpers for the insight features (alerts, best times, stories, weekly summary):
views and interactions per item or source, with one rule for every platform.

Views are page, video, post or impression counts; interactions are likes, comments, shares,
reposts, saves and so on. Bluesky and Mastodon report no views, so their main measure is
interactions.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import MetricPoint
from .goals import GOAL_METRICS

VIEWS = GOAL_METRICS["views"]
INTERACTIONS = GOAL_METRICS["interactions"]
NO_VIEWS = ("bluesky", "mastodon")
STREAMS = ("icecast", "owncast")


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def main_measure(kind: str) -> str:
    """The number that says how well something did on a platform."""
    if kind in STREAMS:
        return "listeners"
    return "interactions" if kind in NO_VIEWS else "views"


def item_values(
    db: Session, item_ids, start: datetime | None = None, end: datetime | None = None
) -> dict[int, dict[str, float]]:
    """{item id: {"views": .., "interactions": ..}} from the daily numbers in [start, end)."""
    ids = list(item_ids)
    out: dict[int, dict[str, float]] = defaultdict(lambda: {"views": 0.0, "interactions": 0.0})
    if not ids:
        return out
    q = (
        select(MetricPoint.item_id, MetricPoint.metric, func.sum(MetricPoint.value))
        .where(
            MetricPoint.item_id.in_(ids),
            MetricPoint.granularity == "day",
            MetricPoint.metric.in_(VIEWS + INTERACTIONS),
        )
        .group_by(MetricPoint.item_id, MetricPoint.metric)
    )
    if start is not None:
        q = q.where(MetricPoint.bucket >= start)
    if end is not None:
        q = q.where(MetricPoint.bucket < end)
    for item_id, metric, value in db.execute(q).all():
        key = "views" if metric in VIEWS else "interactions"
        out[item_id][key] += float(value or 0)
    return out


def typical(values: list[float], minimum: int = 5) -> float | None:
    """The median of earlier values; None when there are too few to say what is normal."""
    values = [v for v in values if v is not None]
    if len(values) < minimum:
        return None
    return float(median(values))
