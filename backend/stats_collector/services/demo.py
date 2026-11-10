"""Demo data for screenshots and trying out the dashboard (`stats-collector demo-data`).

Creates two Icecast mounts and one Owncast server marked as demo (never polled), with a week
of realistic-looking samples up to now, and rolls them up.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ContentItem, Source, StreamSample, utcnow
from .rollup import rollup

STEP = timedelta(seconds=60)


def _curve(ts: datetime, base: float, morning: float, evening: float) -> float:
    h = ts.astimezone(UTC).hour + ts.minute / 60 + 1  # roughly Amsterdam time
    v = base + morning * math.exp(-((h - 8) ** 2) / 4) + evening * math.exp(-((h - 20) ** 2) / 6)
    if ts.weekday() >= 5:
        v *= 0.8
    return max(0.0, v * random.uniform(0.9, 1.1))


def create_demo(db: Session, days: int = 7, now: datetime | None = None) -> int:
    random.seed(42)
    now = (now or utcnow()).replace(second=0, microsecond=0)
    if db.execute(select(Source).where(Source.name.like("Demo %"))).first():
        return 0
    radio = Source(kind="icecast", name="Demo Radio", config={"url": "https://radio.example.org", "demo": True,
                                                                "mounts": ["/live", "/jazz"]},
                   enabled=True, last_ok_at=now, last_poll_at=now)
    tv = Source(kind="owncast", name="Demo TV", config={"url": "https://tv.example.org", "demo": True},
                webhook_token="demo-token-not-used-anywhere", enabled=True, last_ok_at=now, last_poll_at=now)
    db.add_all([radio, tv])
    db.flush()
    live = ContentItem(source_id=radio.id, kind="mount", external_id="/live", title="Radio Live")
    jazz = ContentItem(source_id=radio.id, kind="mount", external_id="/jazz", title="Jazz")
    db.add_all([live, jazz])
    db.flush()
    start = now - timedelta(days=days)
    rows = []
    ts = start
    show = None
    while ts <= now:
        rows.append(dict(source_id=radio.id, item_id=live.id, ts=ts, online=True, value=round(_curve(ts, 18, 70, 45)),
                         extra={"now_playing": "Ochtendshow" if 6 <= ts.hour < 9 else "Muziek"}))
        rows.append(dict(source_id=radio.id, item_id=jazz.id, ts=ts, online=True, value=round(_curve(ts, 6, 4, 14)),
                         extra={}))
        hour = ts.hour
        on_air = 6 <= hour < 8 or 18 <= hour < 20 or ts > now - timedelta(minutes=50)
        if on_air:
            if ts > now - timedelta(minutes=50):
                key, title = "now", "Live: gemeenteraad"
            elif hour < 12:
                key, title = ts.strftime("%Y-%m-%dT06"), "Ochtendjournaal"
            else:
                key, title = ts.strftime("%Y-%m-%dT18"), "Avondshow"
            if show is None or show.external_id != f"broadcast:{key}":
                show = ContentItem(source_id=tv.id, kind="broadcast", external_id=f"broadcast:{key}", title=title,
                                   published_at=ts, ended_at=None)
                db.add(show)
                db.flush()
            show.ended_at = ts + STEP if key != "now" else None
            rows.append(dict(source_id=tv.id, item_id=show.id, ts=ts, online=True, value=round(_curve(ts, 12, 50, 60)),
                             extra={}))
        else:
            rows.append(dict(source_id=tv.id, item_id=None, ts=ts, online=False, value=0, extra={}))
        ts += STEP
    db.bulk_insert_mappings(StreamSample, [{**r, "tenant_id": 1} for r in rows])
    for s in (radio, tv):
        s.poll_seconds = 60
    db.commit()
    rollup(db, since=start, now=now)
    return len(rows)
