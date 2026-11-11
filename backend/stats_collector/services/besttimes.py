"""Best posting times: on which weekday and hour a channel's items do best.

Every item (article, post, video) published in the chosen period counts once, in the hour of the
week it was published (organisation time zone). Its score is what it reached in its first seven
days (views; interactions on Bluesky and Mastodon), so older items do not win by having had more
time. Items younger than two days are left out because their numbers are not complete yet.

Per hour of the week the result holds the number of items and their average; `index` compares
that average with the channel's overall average (100 = as usual). A slot needs at least
`MIN_ITEMS` items to be recommended.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ContentItem, MetricPoint, Source, utcnow
from .measures import INTERACTIONS, NO_VIEWS, VIEWS, aware
from .rollup import org_timezone

FIRST_DAYS = timedelta(days=7)
SETTLE = timedelta(days=2)
MIN_ITEMS = 3
BEST = 5


def best_times(db: Session, source: Source, days: int = 90, now: datetime | None = None) -> dict:
    now = now or utcnow()
    tz = org_timezone(db)
    measure = "interactions" if source.kind in NO_VIEWS else "views"
    metrics = INTERACTIONS if measure == "interactions" else VIEWS
    items = list(
        db.execute(
            select(ContentItem).where(
                ContentItem.source_id == source.id,
                ContentItem.published_at >= now - timedelta(days=days),
                ContentItem.published_at <= now - SETTLE,
            )
        ).scalars()
    )
    published = {i.id: aware(i.published_at) for i in items}
    scores: dict[int, float] = dict.fromkeys(published, 0.0)
    if items:
        for item_id, bucket, value in db.execute(
            select(MetricPoint.item_id, MetricPoint.bucket, MetricPoint.value).where(
                MetricPoint.item_id.in_(list(published)),
                MetricPoint.granularity == "day",
                MetricPoint.metric.in_(metrics),
            )
        ).all():
            # Day buckets start at local midnight; count the days that begin before the 7 days are over.
            if aware(bucket) < published[item_id] + FIRST_DAYS:
                scores[item_id] += float(value or 0)

    cells: dict[tuple[int, int], list[float]] = defaultdict(list)
    for item_id, when in published.items():
        local = when.astimezone(tz)
        cells[(local.weekday(), local.hour)].append(scores[item_id])
    overall = mean(scores.values()) if scores else 0.0

    def index(avg: float) -> int | None:
        return round(avg / overall * 100) if overall else None

    grid = [
        {"weekday": wd, "hour": h, "items": len(v), "avg": round(mean(v), 1), "index": index(mean(v))}
        for (wd, h), v in sorted(cells.items())
    ]
    by_day = []
    for wd in range(7):
        v = [x for (d, _), xs in cells.items() if d == wd for x in xs]
        by_day.append(
            {
                "weekday": wd,
                "items": len(v),
                "avg": round(mean(v), 1) if v else 0,
                "index": index(mean(v)) if v else None,
            }
        )
    by_hour = []
    for h in range(24):
        v = [x for (_, hh), xs in cells.items() if hh == h for x in xs]
        by_hour.append(
            {"hour": h, "items": len(v), "avg": round(mean(v), 1) if v else 0, "index": index(mean(v)) if v else None}
        )
    best = sorted((c for c in grid if c["items"] >= MIN_ITEMS), key=lambda c: -c["avg"])[:BEST]
    few = not best  # too few items per hour yet: show the best hours anyway, marked as uncertain
    if few:
        best = sorted(grid, key=lambda c: (-c["avg"], -c["items"]))[:BEST]
    return {
        "source": {"id": source.id, "name": source.name, "kind": source.kind},
        "days": days,
        "measure": measure,
        "items": len(items),
        "average": round(overall, 1),
        "min_items": MIN_ITEMS,
        "grid": grid,
        "by_day": by_day,
        "by_hour": by_hour,
        "best": best,
        "few": few,
    }
