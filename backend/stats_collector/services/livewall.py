"""Live wall snapshots: the last hour per channel, computed by the worker every minute.

The wall service (stats_collector/livewall, port 8081) has no database access. The worker writes one
JSON snapshot per wall to Redis (key sc:wall:<sha256 of token>, kept for 10 minutes) and, as a
fallback when Redis is not available, to a file under <data_dir>/livewall/. The wall service only
reads those snapshots. A snapshot also carries the wall's title, colours and allowed IP addresses.

Channels and how fresh they are:
  icecast, owncast  live: listeners or viewers from the polls (every ~30 s), in 5-minute bars
  wordpress         live: page views per minute, from the change in today's views between snapshots
YouTube, Facebook and Instagram report whole days only, so they are not on the wall.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import LiveWall, MetricPoint, Source, StreamSample, utcnow
from .metrics import WEB_VIEWS
from .rollup import local_day_start, org_timezone

log = logging.getLogger(__name__)

WALL_KINDS = ("icecast", "owncast", "wordpress")
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
        select(StreamSample.ts, func.sum(StreamSample.value), func.max(StreamSample.online))
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


def snapshot(db: Session, wall: LiveWall, theme: dict, now: datetime | None = None) -> dict:
    now = now or utcnow()
    start = now - BAR * BARS
    stmt = (
        select(Source).where(Source.kind.in_(WALL_KINDS), Source.enabled.is_(True)).order_by(Source.kind, Source.name)
    )
    if wall.source_ids:
        stmt = stmt.where(Source.id.in_([int(i) for i in wall.source_ids]))
    channels = []
    for s in db.execute(stmt).scalars():
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
                "color": (theme.get("channels") or {}).get(_platform(s.kind), "#2FB8FF"),
                "unit": unit,
                "now": now_value,
                "online": online,
                "bars": bars,
                "peak": max(bars) if bars else 0,
                "freshness": "live",
            }
        )
    return {
        "title": wall.title or wall.name,
        "app_name": theme.get("app_name") or "Stats Collector",
        "colors": theme.get("liveWall") or {},
        "fonts": theme.get("fonts") or {},
        "allow_ips": wall.allow_ips or "",
        "at": now.isoformat(),
        "bar_minutes": 5,
        "channels": channels,
    }


def publish(db: Session, now: datetime | None = None) -> int:
    """Compute and store the snapshot of every enabled wall."""
    from ..api.settings import effective_theme

    theme = effective_theme(db)
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
