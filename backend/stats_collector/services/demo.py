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
    return result["hours"] + result["days"]
