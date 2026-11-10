"""Demo data for screenshots and trying out the dashboard (`stats-collector demo-data`).

Creates two Icecast mounts and one Owncast server marked as demo (never polled), with a week
of realistic-looking samples up to now, and rolls them up. Also a demo WordPress site with a month
of articles, editors and website numbers, stored through the same code as the plugin's batches.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ContentItem, Source, StreamSample, utcnow
from .rollup import rollup
from .wordpress import ingest

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
    radio = Source(
        kind="icecast",
        name="Demo Radio",
        config={"url": "https://radio.example.org", "demo": True, "mounts": ["/live", "/jazz"]},
        enabled=True,
        last_ok_at=now,
        last_poll_at=now,
    )
    tv = Source(
        kind="owncast",
        name="Demo TV",
        config={"url": "https://tv.example.org", "demo": True},
        webhook_token="demo-token-not-used-anywhere",
        enabled=True,
        last_ok_at=now,
        last_poll_at=now,
    )
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
        rows.append(
            dict(
                source_id=radio.id,
                item_id=live.id,
                ts=ts,
                online=True,
                value=round(_curve(ts, 18, 70, 45)),
                extra={"now_playing": "Ochtendshow" if 6 <= ts.hour < 9 else "Muziek"},
            )
        )
        rows.append(
            dict(source_id=radio.id, item_id=jazz.id, ts=ts, online=True, value=round(_curve(ts, 6, 4, 14)), extra={})
        )
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
                show = ContentItem(
                    source_id=tv.id,
                    kind="broadcast",
                    external_id=f"broadcast:{key}",
                    title=title,
                    published_at=ts,
                    ended_at=None,
                )
                db.add(show)
                db.flush()
            show.ended_at = ts + STEP if key != "now" else None
            rows.append(
                dict(
                    source_id=tv.id, item_id=show.id, ts=ts, online=True, value=round(_curve(ts, 12, 50, 60)), extra={}
                )
            )
        else:
            rows.append(dict(source_id=tv.id, item_id=None, ts=ts, online=False, value=0, extra={}))
        ts += STEP
    db.bulk_insert_mappings(StreamSample, [{**r, "tenant_id": 1} for r in rows])
    for s in (radio, tv):
        s.poll_seconds = 60
    db.commit()
    rollup(db, since=start, now=now)
    return len(rows) + create_demo_site(db, now=now)


TITLES = [
    "Nieuwe brug over het kanaal geopend",
    "Gemeenteraad stemt in met woningbouwplan",
    "Zwembad gaat in de zomer langer open",
    "Lokale bakker wint landelijke prijs",
    "Wegwerkzaamheden op de Dorpsstraat",
    "Voetbalclub promoveert na spannende finale",
    "Bibliotheek start met taalcafé",
    "Storm zorgt voor omgevallen bomen",
    "Nieuwe huisartsenpraktijk in het centrum",
    "Kermis trekt recordaantal bezoekers",
    "Basisschool krijgt groen schoolplein",
    "Wethouder presenteert begroting",
    "Fietspad langs de dijk vernieuwd",
    "Jongeren organiseren muziekfestival",
    "Markt verhuist tijdelijk naar het plein",
    "Raad wil meer laadpalen in de wijk",
    "Oud-burgemeester overleden",
    "Haven breidt uit met nieuwe kade",
]
CATEGORIES = ["Nieuws", "Politiek", "Sport", "Cultuur"]
EDITORS = [(11, "Anne de Vries"), (12, "Mohammed El Amrani"), (13, "Sanne Bakker"), (14, "Tom Visser")]


def create_demo_site(db: Session, days: int = 30, now: datetime | None = None) -> int:
    rnd = random.Random(7)
    now = (now or utcnow()).replace(minute=0, second=0, microsecond=0)
    site = Source(kind="wordpress", name="Demo Website", config={"url": "https://news.example.org", "demo": True})
    site.webhook_token = "sck_demo-not-used-anywhere"
    db.add(site)
    db.flush()
    items, hours, days_rows = [], [], {}
    site_hours: dict[datetime, dict] = {}
    for n, title in enumerate(TITLES):
        post_id = 1000 + n
        published = now - timedelta(hours=rnd.randint(2, days * 24 - 24))
        editor = EDITORS[n % len(EDITORS)]
        pull = rnd.uniform(0.4, 3.0)
        items.append(
            {
                "id": post_id,
                "type": "post",
                "title": title,
                "url": f"https://news.example.org/{post_id}",
                "published_at": published.isoformat(),
                "authors": [editor[0]] + ([EDITORS[(n + 1) % 4][0]] if n % 5 == 0 else []),
                "categories": [CATEGORIES[n % len(CATEGORIES)]],
                "tags": [],
                "comments": rnd.randint(0, 12),
            }
        )
        hour = published
        while hour <= now:
            age = (hour - published).total_seconds() / 3600
            views = round(_curve(hour, 20, 90, 70) * pull * math.exp(-age / 30))
            if views:
                visitors = max(1, round(views * 0.8))
                row = {
                    "hour": hour.isoformat(),
                    "post": post_id,
                    "views": views,
                    "visitors": visitors,
                    "read_seconds": round(views * rnd.uniform(40, 110)),
                    "reads": round(views * rnd.uniform(0.3, 0.6)),
                    "shares": round(views * rnd.uniform(0, 0.04)),
                    "comments": 1 if rnd.random() < views / 400 else 0,
                }
                hours.append(row)
                tot = site_hours.setdefault(hour, {"hour": hour.isoformat(), "post": 0})
                for key in ("views", "visitors", "read_seconds", "reads", "shares", "comments"):
                    tot[key] = tot.get(key, 0) + row[key]
                day = hour.astimezone(ZoneInfo("Europe/Amsterdam")).date().isoformat()
                for post in (0, post_id):
                    d = days_rows.setdefault(
                        (day, post), {"day": day, "post": post, "visitors": 0, "referrers": {}, "devices": {}}
                    )
                    d["visitors"] += round(visitors * 0.85)
                    for key, share in (("google.com", 0.35), ("facebook.com", 0.2), ("instagram.com", 0.08)):
                        d["referrers"][key] = d["referrers"].get(key, 0) + round(views * share)
                    d["referrers"]["direct"] = d["referrers"].get("direct", 0) + round(views * 0.37)
                    for key, share in (("mobile", 0.68), ("desktop", 0.27), ("tablet", 0.05)):
                        d["devices"][key] = d["devices"].get(key, 0) + round(views * share)
            hour += timedelta(hours=1)
    payload = {
        "site": {"name": "Demo Website", "plugin": "demo"},
        "authors": [{"id": i, "name": name} for i, name in EDITORS],
        "items": items,
        "hours": hours + list(site_hours.values()),
        "days": list(days_rows.values()),
    }
    result = ingest(db, site, payload, now=now)
    return result["hours"] + result["days"] + create_demo_channel(db, now=now) + create_demo_social(db, now=now)


VIDEOS = [
    "Raadsvergadering in 3 minuten",
    "Reportage: de nieuwe brug",
    "Interview met de burgemeester",
    "Kermis 2026: de beelden",
    "Sportweekend samengevat",
    "Achter de schermen bij de radio",
    "Uitleg: het woningbouwplan",
    "Jazz op het plein",
]


def create_demo_channel(db: Session, days: int = 60, now: datetime | None = None) -> int:
    """A demo YouTube channel (never synced) with two months of daily numbers."""
    import json
    from zoneinfo import ZoneInfo

    from ..models import MetricPoint
    from ..security import encrypt_secret
    from .youtube import _day_bucket, months_from_days, rebuild_subscribers

    rnd = random.Random(11)
    tz = ZoneInfo("Europe/Amsterdam")
    now = now or utcnow()
    today = now.astimezone(tz).date()
    channel = Source(
        kind="youtube",
        name="Demo YouTube",
        config={
            "demo": True,
            "client_id": "demo.apps.googleusercontent.com",
            "channel_id": "UCdemo",
            "channel_title": "Demo TV",
            "channel_url": "https://www.youtube.com/@demo",
            "subscribers": 4870,
            "video_count": len(VIDEOS),
            "history_done": True,
        },
        last_ok_at=now,
        poll_seconds=3600,
        secret_enc=encrypt_secret(json.dumps({"client_secret": "demo", "refresh_token": "demo"})),
    )
    db.add(channel)
    db.flush()
    rows = 0
    first = today - timedelta(days=days - 1)
    for n, title in enumerate(VIDEOS):
        published = today - timedelta(days=rnd.randint(1, days - 1))
        item = ContentItem(
            source_id=channel.id,
            kind="video",
            external_id=f"demo{n}",
            title=title,
            url=f"https://www.youtube.com/watch?v=demo{n}",
            published_at=datetime.combine(published, datetime.min.time(), tz).astimezone(UTC) + timedelta(hours=17),
            meta={"duration": "PT4M"},
        )
        db.add(item)
        db.flush()
        pull = rnd.uniform(0.5, 3)
        day = published
        while day <= today - timedelta(days=1):  # Analytics lags a day
            age = (day - published).days
            views = round(400 * pull * math.exp(-age / 6) * rnd.uniform(0.8, 1.2)) + rnd.randint(0, 15)
            values = {
                "yt_views": views,
                "yt_watch_minutes": round(views * rnd.uniform(1.2, 2.4)),
                "yt_likes": round(views * 0.04),
                "yt_comments": round(views * 0.005),
                "yt_shares": round(views * 0.01),
                "yt_subs_gained": round(views * 0.006),
            }
            for metric, value in values.items():
                if value:
                    db.add(
                        MetricPoint(
                            source_id=channel.id,
                            item_id=item.id,
                            metric=metric,
                            granularity="day",
                            bucket=_day_bucket(day, tz),
                            value=value,
                        )
                    )
                    rows += 1
            day += timedelta(days=1)
    db.flush()
    # Channel totals per day: the sum of the videos plus some views on older videos.
    from sqlalchemy import func

    for bucket, metric, total in db.execute(
        select(MetricPoint.bucket, MetricPoint.metric, func.sum(MetricPoint.value))
        .where(MetricPoint.source_id == channel.id, MetricPoint.granularity == "day")
        .group_by(MetricPoint.bucket, MetricPoint.metric)
    ).all():
        db.add(
            MetricPoint(
                source_id=channel.id,
                item_id=None,
                metric=metric,
                granularity="day",
                bucket=bucket,
                value=round(total * 1.15),
            )
        )
        if metric == "yt_subs_gained":
            db.add(
                MetricPoint(
                    source_id=channel.id,
                    metric="yt_subs_lost",
                    granularity="day",
                    bucket=bucket,
                    value=round(total * 0.3),
                )
            )
    db.flush()
    months_from_days(db, channel, first, today, tz)
    rebuild_subscribers(db, channel, 4870, today, tz)
    db.commit()
    return rows


POSTS = [
    "New roundabout opens on Monday",
    "Photos: the harbour festival in 20 pictures",
    "Council approves budget for the new library",
    "Live tonight: the election debate",
    "Volunteers clean up the dunes",
    "Behind the scenes at the radio studio",
    "Local team wins the cup final",
    "Road works: what changes for you",
    "Market day in the old town",
    "Interview with the new mayor",
]


def create_demo_social(db: Session, days: int = 60, now: datetime | None = None) -> int:
    """A demo Facebook Page and Instagram account (never synced) with two months of daily numbers."""
    import json
    from zoneinfo import ZoneInfo

    from sqlalchemy import func

    from ..models import MetricPoint
    from ..security import encrypt_secret
    from .followers import day_bucket, rebuild_gauge
    from .meta import months_from_days
    from .metrics import FB_DAY_METRICS, IG_DAY_METRICS

    rnd = random.Random(23)
    tz = ZoneInfo("Europe/Amsterdam")
    now = now or utcnow()
    today = now.astimezone(tz).date()
    first = today - timedelta(days=days - 1)
    rows = 0
    plans = [
        ("facebook", "Demo Facebook", "Demo News", 12840, "fb", 900),
        ("instagram", "Demo Instagram", "@demonews", 6310, "ig", 650),
    ]
    for kind, name, account, followers, p, base in plans:
        source = Source(
            kind=kind,
            name=name,
            config={
                "demo": True,
                "client_id": "123456789",
                "account_id": f"demo-{kind}",
                "account_name": account,
                "account_url": f"https://www.{kind}.com/demonews",
                "followers": followers,
                "history_done": True,
            },
            last_ok_at=now,
            poll_seconds=3600,
            secret_enc=encrypt_secret(json.dumps({"client_secret": "demo", "page_token": "demo"})),
        )
        db.add(source)
        db.flush()
        for n, title in enumerate(rnd.sample(POSTS, 8)):
            published = today - timedelta(days=rnd.randint(0, days - 1))
            item = ContentItem(
                source_id=source.id,
                kind="post",
                external_id=f"demo-{p}-{n}",
                title=title,
                url=f"https://www.{kind}.com/demonews/posts/{n}",
                published_at=datetime.combine(published, datetime.min.time(), tz).astimezone(UTC)
                + timedelta(hours=rnd.randint(7, 20)),
                meta={"reactions": {"like": 0, "love": 0}} if kind == "facebook" else {"media_type": "REELS"},
            )
            db.add(item)
            db.flush()
            pull = rnd.uniform(0.6, 2.5)
            day = published
            total_likes = 0
            while day <= today:
                age = (day - published).days
                views = round(base * 2 * pull * math.exp(-age / 2.5) * rnd.uniform(0.8, 1.2))
                values = {
                    f"{p}_views": views,
                    f"{p}_reach": round(views * 0.7),
                    f"{p}_comments": round(views * 0.006),
                    f"{p}_shares": round(views * 0.008),
                }
                likes = round(views * (0.03 if kind == "facebook" else 0.07))
                total_likes += likes
                if kind == "facebook":
                    values.update({"fb_reactions": likes, "fb_clicks": round(views * 0.02)})
                else:
                    values.update({"ig_likes": likes, "ig_saves": round(views * 0.01)})
                for metric, value in values.items():
                    if value:
                        db.add(
                            MetricPoint(
                                source_id=source.id,
                                item_id=item.id,
                                metric=metric,
                                granularity="day",
                                bucket=day_bucket(day, tz),
                                value=value,
                            )
                        )
                        rows += 1
                day += timedelta(days=1)
            if kind == "facebook":
                item.meta = {
                    "reactions": {"like": round(total_likes * 0.8), "love": total_likes - round(total_likes * 0.8)}
                }
        db.flush()
        # Account totals: the posts plus everything else people saw (older posts, the profile).
        sums = {
            (bucket, metric): total
            for bucket, metric, total in db.execute(
                select(MetricPoint.bucket, MetricPoint.metric, func.sum(MetricPoint.value))
                .where(MetricPoint.source_id == source.id, MetricPoint.granularity == "day")
                .group_by(MetricPoint.bucket, MetricPoint.metric)
            ).all()
        }
        day = first
        while day <= today:
            bucket = day_bucket(day, tz)
            extra = base * rnd.uniform(0.7, 1.3)
            values = {
                f"{p}_views": sums.get((bucket, f"{p}_views"), 0) + extra,
                f"{p}_reach": sums.get((bucket, f"{p}_reach"), 0) + extra * 0.6,
                f"{p}_follows": rnd.randint(4, 25),
            }
            for metric in ("comments", "shares", "reactions", "clicks", "likes", "saves"):
                if (bucket, f"{p}_{metric}") in sums:
                    values[f"{p}_{metric}"] = sums[(bucket, f"{p}_{metric}")]
            if kind == "facebook":
                values["fb_unfollows"] = rnd.randint(1, 8)
                values["fb_engagements"] = sum(values.get(f"fb_{m}", 0) for m in ("reactions", "comments", "shares"))
            else:
                values["ig_profile_views"] = round(extra * 0.08)
            for metric, value in values.items():
                if value:
                    db.add(
                        MetricPoint(
                            source_id=source.id, metric=metric, granularity="day", bucket=bucket, value=round(value)
                        )
                    )
                    rows += 1
            day += timedelta(days=1)
        db.flush()
        months_from_days(db, source, first, today, FB_DAY_METRICS if kind == "facebook" else IG_DAY_METRICS, tz)
        lost = "fb_unfollows" if kind == "facebook" else None
        rebuild_gauge(db, source, f"{p}_followers", f"{p}_follows", lost, {today: followers}, today, tz)
    db.commit()
    return rows
