"""Website overview: what the WordPress plugin tells beyond page views.

Readers now, site searches (and the ones that found nothing), UTM campaigns, scroll depth, the
production of the newsroom (published, scheduled, drafts, pending review and comments) and what
kind of article does well (length, video, featured image, SEO score, updates).

The plugin sends "live" and "production" as a snapshot every minute; they are kept in the source's
config. Searches, campaigns and scroll depth are dimension rows per day (see services/wordpress.py),
article details live in the item's meta.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ContentItem, DimensionPoint, ItemPerson, MetricPoint, Person, Source, utcnow
from .measures import aware
from .metrics import WEB_READ_SECONDS, WEB_READS, WEB_VIEWS
from .rollup import local_day_start, next_local_day, org_timezone

LIVE_FRESH = timedelta(minutes=3)
LENGTH_BANDS = ((0, 300, "short"), (300, 600, "medium"), (600, 1000, "long"), (1000, 10**9, "very_long"))
SEO_BANDS = ((70, 101, "good"), (40, 70, "ok"), (0, 40, "poor"))
TOP = 25


def sites(db: Session, source_id: int | None = None) -> list[Source]:
    stmt = select(Source).where(Source.kind == "wordpress").order_by(Source.name)
    if source_id is not None:
        stmt = stmt.where(Source.id == source_id)
    return list(db.execute(stmt).scalars())


def live(db: Session, sources: list[Source], now: datetime | None = None) -> dict:
    """Readers in the last five minutes over the sites, with the most read articles right now.
    `readers` is None when no site sent a fresh count (plugin older than 0.4 or not sending)."""
    now = now or utcnow()
    readers: int | None = None
    per_post: dict[tuple[int, str], int] = {}
    for s in sources:
        snap = (s.config or {}).get("live")
        if not isinstance(snap, dict):
            continue
        try:
            at = datetime.fromisoformat(snap.get("at") or "")
        except ValueError:
            continue
        if now - aware(at) > LIVE_FRESH:
            continue
        readers = (readers or 0) + int(snap.get("readers") or 0)
        for post, n in (snap.get("posts") or {}).items():
            per_post[(s.id, str(post))] = int(n)
    items = []
    if per_post:
        rows = db.execute(
            select(ContentItem).where(
                ContentItem.source_id.in_({sid for sid, _ in per_post}),
                ContentItem.external_id.in_({post for _, post in per_post}),
            )
        ).scalars()
        for item in rows:
            n = per_post.get((item.source_id, item.external_id))
            if n:
                items.append({"id": item.id, "title": item.title, "url": item.url, "readers": n})
        items.sort(key=lambda r: -r["readers"])
    return {"readers": readers, "items": items[:10]}


def item_readers_now(item: ContentItem, source: Source | None, now: datetime | None = None) -> int | None:
    if source is None or source.kind != "wordpress":
        return None
    snap = (source.config or {}).get("live")
    if not isinstance(snap, dict):
        return None
    try:
        if (now or utcnow()) - aware(datetime.fromisoformat(snap.get("at") or "")) > LIVE_FRESH:
            return None
    except ValueError:
        return None
    return int((snap.get("posts") or {}).get(item.external_id) or 0)


def _dims(db: Session, source_ids: list[int], start: datetime, end: datetime, dimensions: tuple[str, ...]):
    rows = db.execute(
        select(DimensionPoint.dimension, DimensionPoint.key, func.sum(DimensionPoint.value))
        .where(
            DimensionPoint.source_id.in_(source_ids),
            DimensionPoint.item_id.is_(None),
            DimensionPoint.dimension.in_(dimensions),
            DimensionPoint.bucket >= start,
            DimensionPoint.bucket < end,
        )
        .group_by(DimensionPoint.dimension, DimensionPoint.key)
    ).all()
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for dim, key, total in rows:
        out[dim][key] = out[dim].get(key, 0) + float(total or 0)
    return out


def _top(values: dict[str, float], n: int = TOP) -> list[dict]:
    return [{"key": k, "value": round(v, 1)} for k, v in sorted(values.items(), key=lambda kv: -kv[1])[:n]]


def scroll_summary(values: dict[str, float]) -> dict:
    """Share of views per 25% step and the average depth (the middle of each step; 100 = to the end)."""
    steps = {k: values.get(k, 0.0) for k in ("0", "25", "50", "75", "100")}
    total = sum(steps.values())
    middle = {"0": 12.5, "25": 37.5, "50": 62.5, "75": 87.5, "100": 100}
    avg = round(sum(middle[k] * v for k, v in steps.items()) / total, 1) if total else None
    # "Reached at least x%": what editors usually mean by "scrolled to x".
    reached, running = {}, 0.0
    for k in ("100", "75", "50", "25", "0"):
        running += steps[k]
        reached[k] = round(running / total * 100, 1) if total else 0
    return {"views": int(total), "average": avg, "steps": steps, "reached": reached}


def _item_totals(db: Session, item_ids: list[int], start: datetime, end: datetime) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = defaultdict(dict)
    if not item_ids:
        return out
    rows = db.execute(
        select(MetricPoint.item_id, MetricPoint.metric, func.sum(MetricPoint.value))
        .where(
            MetricPoint.item_id.in_(item_ids),
            MetricPoint.granularity == "day",
            MetricPoint.metric.in_((WEB_VIEWS, WEB_READ_SECONDS, WEB_READS)),
            MetricPoint.bucket >= start,
            MetricPoint.bucket < end,
        )
        .group_by(MetricPoint.item_id, MetricPoint.metric)
    ).all()
    for item_id, metric, total in rows:
        out[item_id][metric] = float(total or 0)
    return out


def _group(name: str, items: list[ContentItem], totals: dict[int, dict[str, float]]) -> dict:
    views = [totals.get(i.id, {}).get(WEB_VIEWS, 0.0) for i in items]
    seconds = sum(totals.get(i.id, {}).get(WEB_READ_SECONDS, 0.0) for i in items)
    reads = sum(totals.get(i.id, {}).get(WEB_READS, 0.0) for i in items)
    total_views = sum(views)
    return {
        "key": name,
        "items": len(items),
        "avg_views": round(mean(views), 1) if views else 0,
        "avg_read_seconds": round(seconds / total_views, 1) if total_views else 0,
        "read_rate": round(reads / total_views * 100, 1) if total_views else 0,
    }


def article_insights(db: Session, source_ids: list[int], start: datetime, end: datetime) -> dict:
    """What kind of article does well: articles published in the period, by length, media, SEO and updates.
    Numbers count what each article reached in the period."""
    items = list(
        db.execute(
            select(ContentItem).where(
                ContentItem.source_id.in_(source_ids),
                ContentItem.kind == "article",
                ContentItem.published_at >= start,
                ContentItem.published_at < end,
            )
        ).scalars()
    )
    known = [i for i in items if "words" in (i.meta or {})]
    totals = _item_totals(db, [i.id for i in items], start, end)

    def meta(i: ContentItem) -> dict:
        return i.meta or {}

    length = [
        _group(name, [i for i in known if lo <= int(meta(i).get("words") or 0) < hi], totals)
        for lo, hi, name in LENGTH_BANDS
    ]
    media = [
        _group("video", [i for i in known if meta(i).get("video")], totals),
        _group("no_video", [i for i in known if not meta(i).get("video")], totals),
        _group("featured_image", [i for i in known if meta(i).get("featured_image")], totals),
        _group("no_featured_image", [i for i in known if not meta(i).get("featured_image")], totals),
    ]
    updates = [
        _group("updated", [i for i in known if int(meta(i).get("updates") or 0) > 0], totals),
        _group("not_updated", [i for i in known if not int(meta(i).get("updates") or 0)], totals),
    ]
    with_seo = [i for i in known if isinstance(meta(i).get("seo"), dict)]
    seo_bands = []
    for lo, hi, name in SEO_BANDS:
        band = [i for i in with_seo if meta(i)["seo"].get("score") is not None and lo <= meta(i)["seo"]["score"] < hi]
        seo_bands.append(_group(name, band, totals))
    words = [int(meta(i).get("words") or 0) for i in known]
    return {
        "articles": len(items),
        "with_details": len(known),
        "avg_words": round(mean(words)) if words else None,
        "length": length,
        "media": media,
        "updates": updates,
        "seo": {
            "articles": len(with_seo),
            "without_keyword": sum(1 for i in with_seo if not meta(i)["seo"].get("keyword")),
            "bands": seo_bands,
        },
    }


def production(db: Session, sources: list[Source], start: datetime, end: datetime, tz, show_people: bool) -> dict:
    """Published articles per day and per editor, plus the pipeline the plugin reports."""
    source_ids = [s.id for s in sources]
    published = list(
        db.execute(
            select(ContentItem).where(
                ContentItem.source_id.in_(source_ids),
                ContentItem.kind == "article",
                ContentItem.published_at >= start,
                ContentItem.published_at < end,
            )
        ).scalars()
    )
    days: dict[str, int] = {}
    day = local_day_start(start, tz)
    while day < end:
        days[day.astimezone(tz).date().isoformat()] = 0
        day = next_local_day(day, tz)
    for i in published:
        key = aware(i.published_at).astimezone(tz).date().isoformat()
        if key in days:
            days[key] += 1
    pipeline = {"scheduled": 0, "drafts": 0, "pending": 0, "pending_comments": 0}
    scheduled: list[dict] = []
    reported = False
    for s in sources:
        snap = (s.config or {}).get("production")
        if not isinstance(snap, dict):
            continue
        reported = True
        for key in pipeline:
            pipeline[key] += int(snap.get(key) or 0)
        for row in snap.get("scheduled_items") or []:
            scheduled.append({**row, "source": s.name})
    names = {}
    if show_people:
        ids = {r.get("person_id") for r in scheduled if r.get("person_id")}
        names = dict(db.execute(select(Person.id, Person.display_name).where(Person.id.in_(ids))).all()) if ids else {}
    scheduled.sort(key=lambda r: r.get("at") or "")
    out = {
        "published": len(published),
        "updated": sum(1 for i in published if int((i.meta or {}).get("updates") or 0) > 0),
        "per_day": [{"day": k, "count": v} for k, v in days.items()],
        "pipeline": pipeline if reported else None,
        "scheduled": [
            {
                "title": r.get("title") or "",
                "at": r.get("at"),
                "source": r["source"],
                **({"author": names.get(r.get("person_id"))} if show_people else {}),
            }
            for r in scheduled[:20]
        ],
    }
    if show_people:
        per: dict[int, int] = defaultdict(int)
        if published:
            for pid, _ in db.execute(
                select(ItemPerson.person_id, ItemPerson.item_id).where(
                    ItemPerson.item_id.in_([i.id for i in published]), ItemPerson.role == "author"
                )
            ).all():
                per[pid] += 1
        people = (
            dict(db.execute(select(Person.id, Person.display_name).where(Person.id.in_(list(per)))).all())
            if per
            else {}
        )
        out["by_editor"] = sorted(
            ({"id": pid, "name": people.get(pid, "?"), "published": n} for pid, n in per.items()),
            key=lambda r: -r["published"],
        )
    return out


def overview(
    db: Session, start: datetime, end: datetime, source_id: int | None = None, show_people: bool = False
) -> dict:
    tz = org_timezone(db)
    chosen = sites(db, source_id)
    ids = [s.id for s in chosen]
    # Dimensions are per local day: a 24-hour window shows today and yesterday.
    dim_start = local_day_start(start, tz)
    dims = _dims(db, ids, dim_start, end, ("search", "search_empty", "campaign", "scroll", "referrer", "device"))
    searches, empty = dims.get("search", {}), dims.get("search_empty", {})
    campaigns = []
    for key, value in sorted(dims.get("campaign", {}).items(), key=lambda kv: -kv[1])[:TOP]:
        source, medium, name = (key.split("|") + ["", "", ""])[:3]
        campaigns.append({"source": source, "medium": medium, "campaign": name, "views": round(value)})
    return {
        "sources": [{"id": s.id, "name": s.name, "plugin": (s.config or {}).get("plugin_version")} for s in sites(db)],
        "live": live(db, chosen),
        "searches": {
            "total": round(sum(searches.values())),
            "empty": round(sum(empty.values())),
            "top": _top(searches),
            "top_empty": _top(empty),
        },
        "campaigns": campaigns,
        "scroll": scroll_summary(dims.get("scroll", {})),
        "referrers": _top(dims.get("referrer", {}), 10),
        "devices": _top(dims.get("device", {}), 5),
        "production": production(db, chosen, start, end, tz, show_people),
        "articles": article_insights(db, ids, start, end),
    }
