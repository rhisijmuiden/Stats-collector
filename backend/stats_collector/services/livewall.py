"""Live wall snapshots, computed by the worker every minute.

The wall service (stats_collector/livewall, port 8081) has no database access. The worker writes one
JSON snapshot per wall to Redis (key sc:wall:<sha256 of token>, kept for 10 minutes) and, as a
fallback when Redis is not available, to a file under <data_dir>/livewall/. The wall service only
reads those snapshots. A snapshot also carries the wall's title, colours, layout and allowed IP
addresses.

What a snapshot holds:
  channels  live channels, the last hour in 5-minute bars:
              icecast, owncast  listeners or viewers from the polls (every ~30 s)
              wordpress         page views per minute, from the change in today's views between runs
  socials   one entry per social source (YouTube, Facebook, Instagram, Threads, X, Bluesky,
            Mastodon): its main number for the latest day with data, the last 7 days, followers,
            the change in followers and the progress of a followers goal for that source alone.
            These platforms report per day and are synced every one to three hours, so the time
            of the last sync goes along (`updated`).
  totals    live audience now, views and interactions today and yesterday, 7 days of both
  top       today's best items over all channels by views (yesterday's early in the morning),
            with the first author; `rising` is what gained most views in the last hour
  goals     the active goals marked for the wall (followers first, also weekly and monthly goals),
            with their progress and the expected date to reach them
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import secrets
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    ContentItem,
    Goal,
    ItemLink,
    ItemPerson,
    LiveWall,
    MetricPoint,
    Person,
    Source,
    StreamSample,
    utcnow,
)
from .goals import GOAL_METRICS
from .metrics import (
    BSKY_FOLLOWERS,
    FB_FOLLOWERS,
    FB_VIEWS,
    IG_FOLLOWERS,
    IG_VIEWS,
    MASTO_FOLLOWERS,
    TH_FOLLOWERS,
    TH_VIEWS,
    WEB_VIEWS,
    X_FOLLOWERS,
    X_IMPRESSIONS,
    YT_SUBSCRIBERS,
    YT_VIEWS,
)
from .rollup import local_day_start, org_timezone

log = logging.getLogger(__name__)

LIVE_KINDS = ("icecast", "owncast", "wordpress")
SOCIAL_KINDS = ("facebook", "instagram", "youtube", "threads", "x", "bluesky", "mastodon")
WALL_KINDS = LIVE_KINDS + SOCIAL_KINDS
LAYOUTS = ("rotate", "overview", "stories")
# The main number of a social tile: views where the platform reports them, else interactions.
SOCIAL_VIEWS = {
    "facebook": FB_VIEWS,
    "instagram": IG_VIEWS,
    "youtube": YT_VIEWS,
    "threads": TH_VIEWS,
    "x": X_IMPRESSIONS,
}
FOLLOWER_GAUGE = {
    "facebook": FB_FOLLOWERS,
    "instagram": IG_FOLLOWERS,
    "youtube": YT_SUBSCRIBERS,
    "threads": TH_FOLLOWERS,
    "x": X_FOLLOWERS,
    "bluesky": BSKY_FOLLOWERS,
    "mastodon": MASTO_FOLLOWERS,
}
VIEW_METRICS = GOAL_METRICS["views"]
INTERACTION_METRICS = GOAL_METRICS["interactions"]
DAYS = 7  # days of history on a social tile
TOP = 10  # items in the top stories
RISING_WINDOW = timedelta(hours=1)
BARS = 12  # 5-minute bars over the last hour
BAR = timedelta(minutes=5)
TTL = 600
PREFIX = "sc:wall:"


def new_token() -> str:
    return secrets.token_urlsafe(24)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ----------------------------------------------------------------------------- store (Redis or files)


def _redis():
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)
        client.ping()
        return client
    except Exception:  # noqa: BLE001 - not installed or not reachable: use files
        return None


def _dir() -> Path:
    d = get_settings().data_dir / "livewall"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:  # the wall service only reads
        pass
    return d


def store_put(key: str, value: dict, ttl: int = TTL) -> None:
    data = json.dumps(value, separators=(",", ":"))
    r = _redis()
    if r is not None:
        r.set(PREFIX + key, data, ex=ttl)
        return
    path = _dir() / f"{key}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data)
    tmp.replace(path)


def store_get(key: str) -> dict | None:
    r = _redis()
    if r is not None:
        raw = r.get(PREFIX + key)
        return json.loads(raw) if raw else None
    path = _dir() / f"{key}.json"
    if not path.exists() or path.stat().st_mtime < datetime.now().timestamp() - TTL:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def store_delete(key: str) -> None:
    r = _redis()
    if r is not None:
        r.delete(PREFIX + key)
    (_dir() / f"{key}.json").unlink(missing_ok=True)


# ----------------------------------------------------------------------------- channels


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _stream_bars(db: Session, source: Source, start: datetime, now: datetime) -> tuple[list[float], float, bool]:
    """Average audience per 5 minutes, the audience at the last poll and whether it is on air."""
    rows = db.execute(
        select(
            StreamSample.ts,
            func.sum(StreamSample.value),
            # max() of a boolean does not exist in PostgreSQL; count as 0/1 instead.
            func.max(case((StreamSample.online.is_(True), 1), else_=0)),
        )
        .where(StreamSample.source_id == source.id, StreamSample.ts >= start, StreamSample.ts <= now)
        .group_by(StreamSample.ts)
        .order_by(StreamSample.ts)
    ).all()
    acc: dict[int, list[float]] = defaultdict(list)
    for ts, value, _online in rows:
        i = int((_aware(ts) - start) / BAR)
        if 0 <= i < BARS:
            acc[i].append(float(value or 0))
    bars = [round(sum(acc[i]) / len(acc[i]), 1) if acc.get(i) else 0.0 for i in range(BARS)]
    fresh = [r for r in rows if _aware(r[0]) >= now - timedelta(seconds=max(120, 3 * source.poll_seconds))]
    now_value = float(fresh[-1][1] or 0) if fresh else 0.0
    return bars, now_value, bool(fresh and fresh[-1][2])


def _views_today(db: Session, source: Source, now: datetime) -> float:
    start = local_day_start(now, org_timezone(db))
    total = db.execute(
        select(func.sum(MetricPoint.value)).where(
            MetricPoint.source_id == source.id,
            MetricPoint.item_id.is_(None),
            MetricPoint.granularity == "hour",
            MetricPoint.metric == WEB_VIEWS,
            MetricPoint.bucket >= start,
        )
    ).scalar_one()
    return float(total or 0)


def website_minutes(db: Session, source: Source, now: datetime) -> list[tuple[str, float]]:
    """Page views per minute over the last hour, from the change in today's total between runs.

    The plugin sends the running total of the current hour every minute, so the change in today's
    total between two runs is what came in between. The minutes are kept in the store."""
    key = f"state-web-{source.id}"
    state = store_get(key) or {}
    total = _views_today(db, source, now)
    minute = now.replace(second=0, microsecond=0).isoformat()
    minutes: list[tuple[str, float]] = [tuple(m) for m in state.get("minutes", [])]  # type: ignore[misc]
    last_total = state.get("total")
    if last_total is not None and state.get("minute") != minute:
        delta = total - last_total if total >= last_total else total  # a new day starts at zero
        minutes.append((minute, round(max(delta, 0.0), 1)))
    cutoff = (now - timedelta(hours=1)).isoformat()
    minutes = [m for m in minutes if m[0] > cutoff]
    if state.get("minute") != minute:
        store_put(key, {"total": total, "minute": minute, "minutes": minutes}, ttl=7200)
    return minutes


def _website_bars(db: Session, source: Source, start: datetime, now: datetime) -> tuple[list[float], float]:
    bars = [0.0] * BARS
    minutes = website_minutes(db, source, now)
    for iso, value in minutes:
        i = int((datetime.fromisoformat(iso) - start) / BAR)
        if 0 <= i < BARS:
            bars[i] += value
    last5 = sum(v for iso, v in minutes if datetime.fromisoformat(iso) >= now - BAR)
    return [round(b, 1) for b in bars], round(last5, 1)


def _platform(kind: str) -> str:
    return "website" if kind == "wordpress" else kind


def _day_values(db: Session, ids: list[int], first: datetime) -> dict[int, dict[str, dict[datetime, float]]]:
    """Per source and metric, the daily values since `first` (whole sources, not items)."""
    out: dict[int, dict[str, dict[datetime, float]]] = defaultdict(lambda: defaultdict(dict))
    if not ids:
        return out
    metrics = tuple(dict.fromkeys((*VIEW_METRICS, *INTERACTION_METRICS, *FOLLOWER_GAUGE.values())))
    rows = db.execute(
        select(MetricPoint.source_id, MetricPoint.metric, MetricPoint.bucket, func.sum(MetricPoint.value))
        .where(
            MetricPoint.source_id.in_(ids),
            MetricPoint.item_id.is_(None),
            MetricPoint.granularity == "day",
            MetricPoint.metric.in_(metrics),
            MetricPoint.bucket >= first,
        )
        .group_by(MetricPoint.source_id, MetricPoint.metric, MetricPoint.bucket)
    ).all()
    for sid, metric, bucket, value in rows:
        out[sid][metric][_aware(bucket)] = float(value or 0)
    return out


def _sum_days(values: dict[str, dict[datetime, float]], metrics, days: list[datetime]) -> list[float]:
    return [round(sum(values.get(m, {}).get(d, 0.0) for m in metrics), 1) for d in days]


def _social(
    source: Source, values: dict[str, dict[datetime, float]], days: list[datetime], goal: dict | None, color: str
) -> dict:
    view = SOCIAL_VIEWS.get(source.kind)
    measure = "views" if view else "interactions"
    series = _sum_days(values, (view,) if view else INTERACTION_METRICS, days)
    interactions = _sum_days(values, INTERACTION_METRICS, days)
    # The latest day with a number: today, or (YouTube reports a day or two late) a day before.
    latest = len(days) - 1
    while latest > len(days) - 4 and not series[latest]:
        latest -= 1
    if not series[latest]:
        latest = len(days) - 1
    gauge = values.get(FOLLOWER_GAUGE.get(source.kind, ""), {})
    seen = [gauge[d] for d in days if d in gauge]
    followers = seen[-1] if seen else None
    change = round(seen[-1] - seen[-2], 1) if len(seen) >= 2 else None
    return {
        "id": source.id,
        "name": source.name,
        "kind": source.kind,
        "color": color,
        "measure": measure,
        "value": series[latest],
        "day": days[latest].isoformat(),
        "days": series,
        "interactions": interactions[latest],
        "followers": followers,
        "followers_change": change,
        "goal": goal,
        "updated": _aware(source.last_ok_at).isoformat() if source.last_ok_at else None,
    }


def _goal_out(db: Session, goal: Goal, now: datetime, today: date) -> dict:
    from .goals import progress

    p = progress(db, goal, now)
    eta = None
    if p["status"] != "reached" and p["rate_per_day"] > 0 and (goal.period or "none") == "none":
        days = math.ceil((goal.target - p["current"]) / p["rate_per_day"])
        if 0 < days <= 3650:
            eta = (today + timedelta(days=days)).isoformat()
    return {
        "id": goal.id,
        "name": goal.name,
        "metric": goal.metric,
        "period": goal.period or "none",
        "period_end": p["period_end"],
        "current": p["current"],
        "target": goal.target,
        "progress": p["progress"],
        "status": p["status"],
        "eta": eta,
        "source_ids": [int(i) for i in goal.source_ids or []],
    }


def _goals(db: Session, wall: LiveWall, now: datetime, today: date) -> list[dict]:
    """Active goals marked for the wall (followers first); on a wall with chosen channels, only goals
    within those channels."""
    chosen = {int(i) for i in wall.source_ids or []}
    out = []
    rows = db.execute(
        select(Goal).where(Goal.archived.is_(False), Goal.show_on_wall.is_(True)).order_by(Goal.id)
    ).scalars()
    for g in sorted(rows, key=lambda g: (g.metric != "followers", g.id)):
        if g.end_date and g.end_date < today:
            continue
        ids = {int(i) for i in g.source_ids or []}
        if chosen and (not ids or not ids <= chosen):
            continue
        try:
            out.append(_goal_out(db, g, now, today))
        except Exception:  # noqa: BLE001 - one broken goal must not stop the wall
            log.exception("live wall: goal %s failed", g.id)
    return out


def _top(
    db: Session,
    ids: list[int],
    day: datetime,
    end: datetime,
    colors: dict[int, str],
    kinds: dict[int, str],
    authors: bool,
) -> list[dict]:
    if not ids:
        return []
    rows = db.execute(
        select(MetricPoint.item_id, func.sum(MetricPoint.value).label("v"))
        .where(
            MetricPoint.source_id.in_(ids),
            MetricPoint.item_id.is_not(None),
            MetricPoint.granularity == "day",
            MetricPoint.metric.in_(VIEW_METRICS),
            MetricPoint.bucket >= day,
            MetricPoint.bucket < end,
        )
        .group_by(MetricPoint.item_id)
        .order_by(func.sum(MetricPoint.value).desc())
        .limit(TOP)
    ).all()
    rows = [(i, float(v or 0)) for i, v in rows if v]
    if not rows:
        return []
    items = {i.id: i for i in db.execute(select(ContentItem).where(ContentItem.id.in_([r[0] for r in rows]))).scalars()}
    names: dict[int, str] = {}
    if authors:
        for item_id, name in db.execute(
            select(ItemPerson.item_id, Person.display_name)
            .join(Person, Person.id == ItemPerson.person_id)
            .where(ItemPerson.item_id.in_(list(items)))
            .order_by(ItemPerson.role, Person.display_name)
        ).all():
            names.setdefault(item_id, name)
        # A social post without an author of its own: the author of the article it links to.
        missing = [i for i in items if i not in names]
        if missing:
            for item_id, name in db.execute(
                select(ItemLink.from_item_id, Person.display_name)
                .join(ItemPerson, ItemPerson.item_id == ItemLink.to_item_id)
                .join(Person, Person.id == ItemPerson.person_id)
                .where(ItemLink.from_item_id.in_(missing))
                .order_by(ItemPerson.role, Person.display_name)
            ).all():
                names.setdefault(item_id, name)
    out = []
    for item_id, value in rows:
        item = items.get(item_id)
        if item is None:
            continue
        out.append(
            {
                "id": item.id,
                "title": (item.title or "").strip()[:140] or "(untitled)",
                "kind": kinds.get(item.source_id, ""),
                "color": colors.get(item.source_id, "#2FB8FF"),
                "value": round(value),
                "author": names.get(item.id, "") if authors else "",
            }
        )
    return out


def _rising(wall: LiveWall, top: list[dict], day: str, now: datetime) -> list[dict]:
    """Views gained in the last hour, from the totals the wall had in earlier runs (kept in the store)."""
    key = f"state-top-{wall.id}"
    state = store_get(key) or {}
    minute = now.replace(second=0, microsecond=0).isoformat()
    history: list[list] = [h for h in state.get("history", []) if h[0] >= (now - RISING_WINDOW).isoformat()]
    if state.get("day") != day:
        history = []
    current = {str(t["id"]): t["value"] for t in top}
    if not history or history[-1][0] != minute:
        history.append([minute, current])
        store_put(key, {"day": day, "history": history}, ttl=7200)
    oldest = history[0][1]
    gains = []
    for t in top:
        before = oldest.get(str(t["id"]))
        if before is not None and t["value"] > before:
            gains.append({**t, "gain": round(t["value"] - before)})
    gains.sort(key=lambda t: -t["gain"])
    return gains[:4]


def snapshot(db: Session, wall: LiveWall, theme: dict, now: datetime | None = None) -> dict:
    now = now or utcnow()
    start = now - BAR * BARS
    palette = theme.get("channels") or {}
    stmt = (
        select(Source).where(Source.kind.in_(WALL_KINDS), Source.enabled.is_(True)).order_by(Source.kind, Source.name)
    )
    if wall.source_ids:
        stmt = stmt.where(Source.id.in_([int(i) for i in wall.source_ids]))
    sources = list(db.execute(stmt).scalars())
    colors = {s.id: palette.get(_platform(s.kind), "#2FB8FF") for s in sources}
    kinds = {s.id: _platform(s.kind) for s in sources}

    channels = []
    for s in sources:
        if s.kind not in LIVE_KINDS:
            continue
        if s.kind == "wordpress":
            bars, now_value = _website_bars(db, s, start, now)
            online, unit = True, "views"
        else:
            bars, now_value, online = _stream_bars(db, s, start, now)
            unit = "viewers" if s.kind == "owncast" else "listeners"
        channels.append(
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "color": colors[s.id],
                "unit": unit,
                "now": now_value,
                "online": online,
                "bars": bars,
                "peak": max(bars) if bars else 0,
                "freshness": "live",
            }
        )

    tz = org_timezone(db)
    today_start = local_day_start(now, tz)
    today = now.astimezone(tz).date()
    days = [local_day_start(today_start - timedelta(days=n, hours=-12), tz) for n in range(DAYS - 1, 0, -1)] + [
        today_start
    ]
    day_ids = [s.id for s in sources if s.kind != "icecast" and s.kind != "owncast"]
    values = _day_values(db, day_ids, days[0])

    goals = _goals(db, wall, now, today)
    own_goal: dict[int, dict] = {}
    for g in goals:  # a channel's ring: its own goal, a followers goal first
        if len(g["source_ids"]) == 1:
            own_goal.setdefault(g["source_ids"][0], g)
    socials = [
        _social(s, values[s.id], days, own_goal.get(s.id), colors[s.id]) for s in sources if s.kind in SOCIAL_KINDS
    ]

    views_days = [0.0] * DAYS
    inter_days = [0.0] * DAYS
    for sid in day_ids:
        for n, v in enumerate(_sum_days(values[sid], VIEW_METRICS, days)):
            views_days[n] += v
        for n, v in enumerate(_sum_days(values[sid], INTERACTION_METRICS, days)):
            inter_days[n] += v
    live = sum(c["now"] for c in channels if c["unit"] != "views")

    top = _top(db, day_ids, today_start, now + timedelta(minutes=1), colors, kinds, wall.show_authors)
    top_day = today_start
    if len(top) < 3:  # early in the morning: yesterday's list
        yesterday = days[-2]
        earlier = _top(db, day_ids, yesterday, today_start, colors, kinds, wall.show_authors)
        if len(earlier) > len(top):
            top, top_day = earlier, yesterday
    rising = _rising(wall, top, top_day.isoformat(), now) if top else []

    return {
        "title": wall.title or wall.name,
        "app_name": theme.get("app_name") or "Stats Collector",
        "colors": theme.get("liveWall") or {},
        "fonts": theme.get("fonts") or {},
        "allow_ips": wall.allow_ips or "",
        "layout": wall.layout if wall.layout in LAYOUTS else "rotate",
        "rotate_seconds": max(10, min(300, int(wall.rotate_seconds or 30))),
        "at": now.isoformat(),
        "bar_minutes": 5,
        "channels": channels,
        "socials": socials,
        "totals": {
            "live": live,
            "views_today": round(views_days[-1]),
            "views_yesterday": round(views_days[-2]),
            "interactions_today": round(inter_days[-1]),
            "interactions_yesterday": round(inter_days[-2]),
            "views_days": [round(v) for v in views_days],
            "interactions_days": [round(v) for v in inter_days],
        },
        "top": top,
        "top_day": top_day.isoformat(),
        "today": today_start.isoformat(),
        "rising": rising,
        "goals": goals,
    }


def base_url(db: Session) -> str:
    """Where screens open the walls: the address set under Live walls, else SC_LIVEWALL_URL or port 8081."""
    from . import settings_store

    url = (settings_store.get_section(db, "livewall").get("public_url") or "").strip().rstrip("/")
    return url or get_settings().wall_base_url


def publish(db: Session, now: datetime | None = None) -> int:
    """Compute and store the snapshot of every enabled wall, and the wall service's proxy settings."""
    from ..api.settings import effective_theme
    from . import settings_store

    theme = effective_theme(db)
    try:
        cfg = settings_store.get_section(db, "livewall")
        store_put("config", {"trusted_proxies": cfg.get("trusted_proxies") or ""}, ttl=86400)
    except Exception:  # noqa: BLE001 - the walls themselves matter more
        log.exception("live wall: storing the proxy settings failed")
    n = 0
    for wall in db.execute(select(LiveWall)).scalars():
        if not wall.enabled:
            store_delete(wall.token_hash)
            continue
        try:
            store_put(wall.token_hash, snapshot(db, wall, theme, now))
            n += 1
        except Exception:  # noqa: BLE001 - one wall must not stop the others
            log.exception("live wall %s: snapshot failed", wall.id)
    return n
