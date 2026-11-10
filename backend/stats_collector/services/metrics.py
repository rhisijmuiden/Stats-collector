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

# Facebook Page and Instagram professional account (Graph API, per day). Followers are gauges.
FB_VIEWS = "fb_views"
FB_REACH = "fb_reach"
FB_ENGAGEMENTS = "fb_engagements"
FB_REACTIONS = "fb_reactions"
FB_COMMENTS = "fb_comments"
FB_SHARES = "fb_shares"
FB_CLICKS = "fb_clicks"
FB_VIDEO_VIEWS = "fb_video_views"
FB_FOLLOWS = "fb_follows"
FB_UNFOLLOWS = "fb_unfollows"
FB_FOLLOWERS = "fb_followers"
FB_DAY_METRICS = (
    FB_VIEWS,
    FB_REACH,
    FB_ENGAGEMENTS,
    FB_REACTIONS,
    FB_COMMENTS,
    FB_SHARES,
    FB_CLICKS,
    FB_VIDEO_VIEWS,
    FB_FOLLOWS,
    FB_UNFOLLOWS,
)
IG_VIEWS = "ig_views"
IG_REACH = "ig_reach"
IG_LIKES = "ig_likes"
IG_COMMENTS = "ig_comments"
IG_SHARES = "ig_shares"
IG_SAVES = "ig_saves"
IG_PROFILE_VIEWS = "ig_profile_views"
IG_FOLLOWS = "ig_follows"
IG_FOLLOWERS = "ig_followers"
IG_DAY_METRICS = (IG_VIEWS, IG_REACH, IG_LIKES, IG_COMMENTS, IG_SHARES, IG_SAVES, IG_PROFILE_VIEWS, IG_FOLLOWS)

# Threads (Threads API, per day). Views per day come from the account insights; likes, replies,
# reposts, quotes and shares per day are the sums of what the posts gained.
TH_VIEWS = "th_views"
TH_LIKES = "th_likes"
TH_REPLIES = "th_replies"
TH_REPOSTS = "th_reposts"
TH_QUOTES = "th_quotes"
TH_SHARES = "th_shares"
TH_FOLLOWS = "th_follows"
TH_FOLLOWERS = "th_followers"
TH_POST_METRICS = (TH_VIEWS, TH_LIKES, TH_REPLIES, TH_REPOSTS, TH_QUOTES, TH_SHARES)
TH_DAY_METRICS = (*TH_POST_METRICS, TH_FOLLOWS)

# Bluesky and Mastodon (public APIs, per day). They report no views or reach: only what people did
# with a post, and the follower count. Daily numbers are the change in each post's totals between
# syncs; new followers per day is the change in the follower count (net).
BSKY_LIKES = "bsky_likes"
BSKY_REPOSTS = "bsky_reposts"
BSKY_REPLIES = "bsky_replies"
BSKY_QUOTES = "bsky_quotes"
BSKY_FOLLOWS = "bsky_follows"
BSKY_FOLLOWERS = "bsky_followers"
BSKY_POST_METRICS = (BSKY_LIKES, BSKY_REPOSTS, BSKY_REPLIES, BSKY_QUOTES)
BSKY_DAY_METRICS = (*BSKY_POST_METRICS, BSKY_FOLLOWS)
MASTO_FAVOURITES = "masto_favourites"
MASTO_BOOSTS = "masto_boosts"
MASTO_REPLIES = "masto_replies"
MASTO_FOLLOWS = "masto_follows"
MASTO_FOLLOWERS = "masto_followers"
MASTO_POST_METRICS = (MASTO_FAVOURITES, MASTO_BOOSTS, MASTO_REPLIES)
MASTO_DAY_METRICS = (*MASTO_POST_METRICS, MASTO_FOLLOWS)

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
    Metric("facebook", FB_VIEWS, "count", "sum", "views", "Views", "Weergaven"),
    Metric("facebook", FB_REACH, "count", "sum", "reach", "Reach", "Bereik"),
    Metric("facebook", FB_ENGAGEMENTS, "count", "sum", "interactions", "Post engagements", "Interacties"),
    Metric("facebook", FB_REACTIONS, "count", "sum", "interactions", "Reactions", "Reacties (emoji)"),
    Metric("facebook", FB_COMMENTS, "count", "sum", "interactions", "Comments", "Opmerkingen"),
    Metric("facebook", FB_SHARES, "count", "sum", "interactions", "Shares", "Keren gedeeld"),
    Metric("facebook", FB_CLICKS, "count", "sum", "interactions", "Clicks", "Klikken"),
    Metric("facebook", FB_VIDEO_VIEWS, "count", "sum", "views", "Video views", "Videoweergaven"),
    Metric("facebook", FB_FOLLOWS, "count", "sum", "followers", "New followers", "Nieuwe volgers"),
    Metric("facebook", FB_UNFOLLOWS, "count", "sum", "followers", "Unfollows", "Ontvolgd"),
    Metric("facebook", FB_FOLLOWERS, "count", "gauge", "followers", "Followers", "Volgers"),
    Metric("instagram", IG_VIEWS, "count", "sum", "views", "Views", "Weergaven"),
    Metric("instagram", IG_REACH, "count", "sum", "reach", "Reach", "Bereik"),
    Metric("instagram", IG_LIKES, "count", "sum", "interactions", "Likes", "Likes"),
    Metric("instagram", IG_COMMENTS, "count", "sum", "interactions", "Comments", "Opmerkingen"),
    Metric("instagram", IG_SHARES, "count", "sum", "interactions", "Shares", "Keren gedeeld"),
    Metric("instagram", IG_SAVES, "count", "sum", "interactions", "Saves", "Opgeslagen"),
    Metric("instagram", IG_PROFILE_VIEWS, "count", "sum", "views", "Profile visits", "Profielbezoeken"),
    Metric("instagram", IG_FOLLOWS, "count", "sum", "followers", "New followers", "Nieuwe volgers"),
    Metric("instagram", IG_FOLLOWERS, "count", "gauge", "followers", "Followers", "Volgers"),
    Metric("threads", TH_VIEWS, "count", "sum", "views", "Views", "Weergaven"),
    Metric("threads", TH_LIKES, "count", "sum", "interactions", "Likes", "Likes"),
    Metric("threads", TH_REPLIES, "count", "sum", "interactions", "Replies", "Antwoorden"),
    Metric("threads", TH_REPOSTS, "count", "sum", "interactions", "Reposts", "Reposts"),
    Metric("threads", TH_QUOTES, "count", "sum", "interactions", "Quotes", "Citaten"),
    Metric("threads", TH_SHARES, "count", "sum", "interactions", "Shares", "Keren gedeeld"),
    Metric("threads", TH_FOLLOWS, "count", "sum", "followers", "New followers (net)", "Nieuwe volgers (netto)"),
    Metric("threads", TH_FOLLOWERS, "count", "gauge", "followers", "Followers", "Volgers"),
    Metric("bluesky", BSKY_LIKES, "count", "sum", "interactions", "Likes", "Likes"),
    Metric("bluesky", BSKY_REPOSTS, "count", "sum", "interactions", "Reposts", "Reposts"),
    Metric("bluesky", BSKY_REPLIES, "count", "sum", "interactions", "Replies", "Antwoorden"),
    Metric("bluesky", BSKY_QUOTES, "count", "sum", "interactions", "Quotes", "Citaten"),
    Metric("bluesky", BSKY_FOLLOWS, "count", "sum", "followers", "New followers (net)", "Nieuwe volgers (netto)"),
    Metric("bluesky", BSKY_FOLLOWERS, "count", "gauge", "followers", "Followers", "Volgers"),
    Metric("mastodon", MASTO_FAVOURITES, "count", "sum", "interactions", "Favourites", "Favorieten"),
    Metric("mastodon", MASTO_BOOSTS, "count", "sum", "interactions", "Boosts", "Boosts"),
    Metric("mastodon", MASTO_REPLIES, "count", "sum", "interactions", "Replies", "Antwoorden"),
    Metric("mastodon", MASTO_FOLLOWS, "count", "sum", "followers", "New followers (net)", "Nieuwe volgers (netto)"),
    Metric("mastodon", MASTO_FOLLOWERS, "count", "gauge", "followers", "Followers", "Volgers"),
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
