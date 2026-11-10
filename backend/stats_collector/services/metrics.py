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

# Website metrics (WordPress plugin). Hourly values come from the plugin; daily and monthly
# totals are sums, except unique visitors per day, which the plugin counts itself.
WEB_VIEWS = "web_views"
WEB_VISITORS = "web_visitors"
WEB_READ_SECONDS = "web_read_seconds"
WEB_READS = "web_reads"
WEB_SHARES = "web_shares"
WEB_COMMENTS = "web_comments"
WEB_HOUR_METRICS = (WEB_VIEWS, WEB_VISITORS, WEB_READ_SECONDS, WEB_READS, WEB_SHARES, WEB_COMMENTS)
WEB_SUM_FROM_HOURS = (WEB_VIEWS, WEB_READ_SECONDS, WEB_READS, WEB_SHARES, WEB_COMMENTS)

# YouTube (Analytics API, per day). Subscribers is a gauge: the count at the end of the day.
YT_VIEWS = "yt_views"
YT_WATCH_MINUTES = "yt_watch_minutes"
YT_LIKES = "yt_likes"
YT_COMMENTS = "yt_comments"
YT_SHARES = "yt_shares"
YT_SUBS_GAINED = "yt_subs_gained"
YT_SUBS_LOST = "yt_subs_lost"
YT_SUBSCRIBERS = "yt_subscribers"
YT_DAY_METRICS = (YT_VIEWS, YT_WATCH_MINUTES, YT_LIKES, YT_COMMENTS, YT_SHARES, YT_SUBS_GAINED, YT_SUBS_LOST)

REGISTRY: tuple[Metric, ...] = (
    Metric("icecast", LIVE_AVG, "count", "avg", "live_audience", "Average listeners", "Gemiddeld aantal luisteraars"),
    Metric("icecast", LIVE_PEAK, "count", "max", "live_audience", "Peak listeners", "Piek luisteraars"),
    Metric("icecast", LIVE_MINUTES, "minutes", "sum", "watch_time", "Listening minutes", "Luisterminuten"),
    Metric("owncast", LIVE_AVG, "count", "avg", "live_audience", "Average viewers", "Gemiddeld aantal kijkers"),
    Metric("owncast", LIVE_PEAK, "count", "max", "live_audience", "Peak viewers", "Piek kijkers"),
    Metric("owncast", LIVE_MINUTES, "minutes", "sum", "watch_time", "Viewing minutes", "Kijkminuten"),
    Metric("wordpress", WEB_VIEWS, "count", "sum", "views", "Page views", "Paginaweergaven"),
    Metric("wordpress", WEB_VISITORS, "count", "unique", "reach", "Unique visitors", "Unieke bezoekers"),
    Metric("wordpress", WEB_READ_SECONDS, "seconds", "sum", "watch_time", "Reading time", "Leestijd"),
    Metric("wordpress", WEB_READS, "count", "sum", "interactions", "Engaged reads", "Gelezen artikelen"),
    Metric("wordpress", WEB_SHARES, "count", "sum", "interactions", "Share clicks", "Deelkliks"),
    Metric("wordpress", WEB_COMMENTS, "count", "sum", "interactions", "Comments", "Reacties"),
    Metric("youtube", YT_VIEWS, "count", "sum", "views", "Views", "Weergaven"),
    Metric("youtube", YT_WATCH_MINUTES, "minutes", "sum", "watch_time", "Watch time", "Kijktijd"),
    Metric("youtube", YT_LIKES, "count", "sum", "interactions", "Likes", "Likes"),
    Metric("youtube", YT_COMMENTS, "count", "sum", "interactions", "Comments", "Reacties"),
    Metric("youtube", YT_SHARES, "count", "sum", "interactions", "Shares", "Keren gedeeld"),
    Metric("youtube", YT_SUBS_GAINED, "count", "sum", "followers", "Subscribers gained", "Nieuwe abonnees"),
    Metric("youtube", YT_SUBS_LOST, "count", "sum", "followers", "Subscribers lost", "Verloren abonnees"),
    Metric("youtube", YT_SUBSCRIBERS, "count", "gauge", "followers", "Subscribers", "Abonnees"),
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
