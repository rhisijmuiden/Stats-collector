"""Metric registry: every platform metric with its unit, aggregation and canonical category.

The registry in code is the source of truth; `sync_definitions` mirrors it into the
`metric_definitions` table (run by `stats-collector migrate`), so reports and the API can join on it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MetricDefinition


@dataclass(frozen=True)
class Metric:
    platform: str
    key: str
    unit: str
    aggregation: str
    category: str
    label_en: str
    label_nl: str


# Live audience metrics share keys across Icecast and Owncast so they can be stacked.
LIVE_AVG = "live_avg"
LIVE_PEAK = "live_peak"
LIVE_MINUTES = "live_minutes"
LIVE_METRICS = (LIVE_AVG, LIVE_PEAK, LIVE_MINUTES)

REGISTRY: tuple[Metric, ...] = (
    Metric("icecast", LIVE_AVG, "count", "avg", "live_audience", "Average listeners", "Gemiddeld aantal luisteraars"),
    Metric("icecast", LIVE_PEAK, "count", "max", "live_audience", "Peak listeners", "Piek luisteraars"),
    Metric("icecast", LIVE_MINUTES, "minutes", "sum", "watch_time", "Listening minutes", "Luisterminuten"),
    Metric("owncast", LIVE_AVG, "count", "avg", "live_audience", "Average viewers", "Gemiddeld aantal kijkers"),
    Metric("owncast", LIVE_PEAK, "count", "max", "live_audience", "Peak viewers", "Piek kijkers"),
    Metric("owncast", LIVE_MINUTES, "minutes", "sum", "watch_time", "Viewing minutes", "Kijkminuten"),
)


def sync_definitions(db: Session) -> int:
    existing = {(m.platform, m.key): m for m in db.execute(select(MetricDefinition)).scalars()}
    changed = 0
    for m in REGISTRY:
        row = existing.get((m.platform, m.key))
        if row is None:
            row = MetricDefinition(platform=m.platform, key=m.key)
            db.add(row)
        values = dict(
            unit=m.unit, aggregation=m.aggregation, category=m.category, label_en=m.label_en, label_nl=m.label_nl
        )
        if any(getattr(row, k, None) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(row, k, v)
            changed += 1
    db.commit()
    return changed
