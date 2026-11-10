"""YouTube channels: Google OAuth, the Data API (videos, subscriber count) and the Analytics API.

What is stored, per day (Analytics has no hours and lags one to two days):
  channel  yt_views, yt_watch_minutes, yt_likes, yt_comments, yt_shares, yt_subs_gained, yt_subs_lost
           yt_subscribers  (gauge: today's count from the Data API; earlier days are worked back
                            from it with the daily gains and losses, since YouTube has no history)
  video    the same sums, from a "top videos of that day" report (up to 200 videos per day)
Months are sums of days; the subscriber gauge of a month is its last day.

History: right after connecting, the whole channel history is fetched: the channel totals per
day in one report per year, and the per-video numbers one day per report, newest first, a few
hundred days per run so the daily quotas are never reached. `config.history_until` records how
far back the import has come.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets as pysecrets
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..connectors import ConnectorError
from ..models import ContentItem, MetricPoint, Source, utcnow
from ..security import encrypt_secret
from .collect import source_secrets
from .links import extract_urls
from .metrics import (
    YT_COMMENTS,
    YT_DAY_METRICS,
    YT_LIKES,
    YT_SHARES,
    YT_SUBS_GAINED,
    YT_SUBS_LOST,
    YT_SUBSCRIBERS,
    YT_VIEWS,
    YT_WATCH_MINUTES,
)
from .rollup import local_month_start, next_local_month, org_timezone

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly"

# Analytics report columns -> metric keys
ANALYTICS = {
    "views": YT_VIEWS,
    "estimatedMinutesWatched": YT_WATCH_MINUTES,
    "likes": YT_LIKES,
    "comments": YT_COMMENTS,
    "shares": YT_SHARES,
    "subscribersGained": YT_SUBS_GAINED,
    "subscribersLost": YT_SUBS_LOST,
}
RECENT_DAYS = 5  # days re-read every sync (Analytics fills them in late)
HISTORY_DAYS_PER_RUN = 120
TOP_VIDEOS_PER_DAY = 200
SYNC_EVERY = timedelta(hours=3)
FULL_VIDEO_LIST_EVERY = timedelta(hours=24)


# ----------------------------------------------------------------------------- OAuth


def pkce_pair() -> tuple[str, str]:
    verifier = pysecrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",  # always hand out a refresh token, also when reconnecting
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _client(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), headers={"User-Agent": "StatsCollector/1"})


def exchange_code(client_id: str, client_secret: str, code: str, verifier: str, redirect_uri: str, client=None) -> dict:
    http = _client(client)
    try:
        resp = http.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
    except httpx.HTTPError as exc:
        raise ConnectorError("yt_token_failed") from exc
    data = _json(resp)
    if resp.status_code != 200 or "access_token" not in data:
        raise ConnectorError(f"yt_token_failed: {data.get('error', resp.status_code)}")
    granted = set(str(data.get("scope", "")).split())
    if not set(SCOPES.split()) <= granted:
        raise ConnectorError("yt_scope_missing")
    return data


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class Google:
    """Small API client for one connected channel; refreshes the access token when needed."""

    def __init__(self, source: Source, client: httpx.Client | None = None):
        self.source = source
        self.secrets = source_secrets(source)
        self.http = _client(client)
        self.token: str | None = None
        self.calls = 0

    def _refresh(self) -> str:
        cfg = self.source.config or {}
        refresh = self.secrets.get("refresh_token")
        if not refresh:
            raise ConnectorError("yt_not_connected")
        try:
            resp = self.http.post(
                TOKEN_URL,
                data={
                    "client_id": cfg.get("client_id", ""),
                    "client_secret": self.secrets.get("client_secret", ""),
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"connection_failed: {exc}") from exc
        data = _json(resp)
        if resp.status_code != 200 or "access_token" not in data:
            # invalid_grant: access was revoked, or the app is in testing mode (tokens expire after 7 days)
            raise ConnectorError(f"yt_reconnect: {data.get('error', resp.status_code)}")
        self.token = data["access_token"]
        return self.token

    def get(self, url: str, params: dict) -> dict:
        for attempt in (1, 2):
            token = self.token or self._refresh()
            try:
                resp = self.http.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            except httpx.TimeoutException as exc:
                raise ConnectorError("timeout") from exc
            except httpx.HTTPError as exc:
                raise ConnectorError(f"connection_failed: {exc}") from exc
            self.calls += 1
            if resp.status_code == 401 and attempt == 1:
                self.token = None
                continue
            data = _json(resp)
            if resp.status_code >= 400:
                reason = ""
                errors = (data.get("error") or {}).get("errors") or []
                if errors:
                    reason = errors[0].get("reason", "")
                if resp.status_code == 403 and "quota" in reason.lower():
                    raise ConnectorError("yt_quota")
                if resp.status_code == 403:
                    raise ConnectorError(f"yt_forbidden: {reason or (data.get('error') or {}).get('message', '')}")
                raise ConnectorError(f"http_{resp.status_code}")
            return data
        raise ConnectorError("unauthorized")

    # --- Data API

    def channel(self) -> dict:
        data = self.get(f"{DATA_API}/channels", {"part": "snippet,statistics,contentDetails", "mine": "true"})
        items = data.get("items") or []
        if not items:
            raise ConnectorError("yt_no_channel")
        return items[0]

    def upload_ids(self, playlist: str, max_pages: int | None = None) -> list[str]:
        ids: list[str] = []
        token = None
        pages = 0
        while True:
            params = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50}
            if token:
                params["pageToken"] = token
            data = self.get(f"{DATA_API}/playlistItems", params)
            ids += [i["contentDetails"]["videoId"] for i in data.get("items") or [] if i.get("contentDetails")]
            token = data.get("nextPageToken")
            pages += 1
            if not token or (max_pages and pages >= max_pages):
                return ids

    def videos(self, ids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 50):
            data = self.get(
                f"{DATA_API}/videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[i : i + 50])}
            )
            out += data.get("items") or []
        return out

    # --- Analytics API

    def report(self, start: date, end: date, dimensions: str, **extra) -> list[dict]:
        params = {
            "ids": "channel==MINE",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "metrics": ",".join(ANALYTICS),
            "dimensions": dimensions,
            **extra,
        }
        data = self.get(ANALYTICS_API, params)
        headers = [h.get("name") for h in data.get("columnHeaders") or []]
        return [dict(zip(headers, row, strict=False)) for row in data.get("rows") or []]


# ----------------------------------------------------------------------------- storing


def _day_bucket(day: date, tz) -> datetime:
    return datetime.combine(day, dtime(0), tz).astimezone(UTC)


def _put_day(db: Session, source: Source, item_id: int | None, bucket: datetime, values: dict[str, float]) -> None:
    db.execute(
        delete(MetricPoint).where(
            MetricPoint.source_id == source.id,
            MetricPoint.item_id.is_(None) if item_id is None else MetricPoint.item_id == item_id,
            MetricPoint.granularity == "day",
            MetricPoint.bucket == bucket,
            MetricPoint.metric.in_(tuple(values)),
        )
    )
    for metric, value in values.items():
        if value:
            db.add(
                MetricPoint(
                    tenant_id=source.tenant_id,
                    source_id=source.id,
                    item_id=item_id,
                    metric=metric,
                    granularity="day",
                    bucket=bucket,
                    value=float(value),
                )
            )


def _values(row: dict) -> dict[str, float]:
    return {metric: float(row.get(col) or 0) for col, metric in ANALYTICS.items()}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def upsert_videos(db: Session, source: Source, videos: list[dict]) -> dict[str, ContentItem]:
    items = {
        i.external_id: i
        for i in db.execute(
            select(ContentItem).where(ContentItem.source_id == source.id, ContentItem.kind == "video")
        ).scalars()
    }
    for v in videos:
        vid = v.get("id")
        if not vid:
            continue
        sn = v.get("snippet") or {}
        item = items.get(vid)
        if item is None:
            item = ContentItem(tenant_id=source.tenant_id, source_id=source.id, kind="video", external_id=vid)
            db.add(item)
            items[vid] = item
        item.title = str(sn.get("title") or item.title or vid)[:500]
        item.url = f"https://www.youtube.com/watch?v={vid}"
        item.published_at = _parse_time(sn.get("publishedAt")) or item.published_at
        item.tags = [str(t)[:100] for t in (sn.get("tags") or [])][:50]
        stats = v.get("statistics") or {}
        item.meta = {
            **(item.meta or {}),
            "duration": (v.get("contentDetails") or {}).get("duration"),
            "views_total": int(stats.get("viewCount") or 0),
            "likes_total": int(stats.get("likeCount") or 0),
            "comments": int(stats.get("commentCount") or 0),
            "thumbnail": ((sn.get("thumbnails") or {}).get("medium") or {}).get("url"),
            "links": extract_urls(sn.get("description")),
        }
    db.flush()
    return items


def _video_item(db: Session, source: Source, vid: str, items: dict[str, ContentItem]) -> ContentItem:
    item = items.get(vid)
    if item is None:  # a video that is no longer public: keep its numbers under its id
        item = ContentItem(
            tenant_id=source.tenant_id,
            source_id=source.id,
            kind="video",
            external_id=vid,
            title=vid,
            url=f"https://www.youtube.com/watch?v={vid}",
        )
        db.add(item)
        db.flush()
        items[vid] = item
    return item


def store_channel_days(db: Session, source: Source, rows: list[dict], tz) -> list[date]:
    days = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("day")))
        except ValueError:
            continue
        _put_day(db, source, None, _day_bucket(day, tz), _values(row))
        days.append(day)
    return days


def store_video_day(db: Session, source: Source, day: date, rows: list[dict], items, tz) -> int:
    bucket = _day_bucket(day, tz)
    # Replace the whole day: a video can drop out of the top list when YouTube corrects numbers.
    db.execute(
        delete(MetricPoint).where(
            MetricPoint.source_id == source.id,
            MetricPoint.item_id.is_not(None),
            MetricPoint.granularity == "day",
            MetricPoint.bucket == bucket,
            MetricPoint.metric.in_(YT_DAY_METRICS),
        )
    )
    n = 0
    for row in rows:
        vid = row.get("video")
        if not vid:
            continue
        item = _video_item(db, source, str(vid), items)
        _put_day(db, source, item.id, bucket, {k: v for k, v in _values(row).items() if k not in (YT_SUBS_LOST,)})
        n += 1
    return n


def rebuild_subscribers(db: Session, source: Source, current: int, today: date, tz) -> None:
    """Subscriber count per day, worked back from today's count with the daily gains and losses."""
    from .followers import rebuild_gauge

    rebuild_gauge(db, source, YT_SUBSCRIBERS, YT_SUBS_GAINED, YT_SUBS_LOST, {today: current}, today, tz)


def months_from_days(db: Session, source: Source, first: date, last: date, tz) -> None:
    from .rollup import _sum_from

    month = local_month_start(_day_bucket(first, tz), tz)
    end = _day_bucket(last, tz)
    while month <= end:
        _sum_from(db, source, "day", "month", month, next_local_month(month, tz), YT_DAY_METRICS)
        month = next_local_month(month, tz)


# ----------------------------------------------------------------------------- sync


def connect(db: Session, source: Source, token: dict, client=None) -> dict:
    """Store the refresh token after the Google consent screen and remember the channel."""
    values = {**source_secrets(source), "refresh_token": token.get("refresh_token") or ""}
    if not values["refresh_token"]:
        raise ConnectorError("yt_no_refresh_token")
    source.secret_enc = encrypt_secret(json.dumps(values))
    api = Google(source, client)
    api.token = token.get("access_token")
    ch = api.channel()
    sn = ch.get("snippet") or {}
    source.config = {
        **(source.config or {}),
        "channel_id": ch.get("id"),
        "channel_title": sn.get("title"),
        "channel_url": f"https://www.youtube.com/channel/{ch.get('id')}",
        "channel_started": (sn.get("publishedAt") or "")[:10] or None,
        "history_until": None,
        "history_done": False,
        "last_full_list": None,
    }
    source.last_error = None
    if not source.name:
        source.name = sn.get("title") or "YouTube"
    db.commit()
    return {"channel_id": ch.get("id"), "title": sn.get("title")}


def is_due(source: Source, now: datetime) -> bool:
    if not (source.config or {}).get("channel_id") or (source.config or {}).get("demo"):
        return False
    if not (source.config or {}).get("history_done"):
        return True  # keep importing history every run
    last = source.last_poll_at
    if last is None:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    return now - last >= SYNC_EVERY


def sync(db: Session, source: Source, now: datetime | None = None, client=None) -> dict:
    if (source.config or {}).get("demo"):
        return {"demo": True}
    now = now or utcnow()
    tz = org_timezone(db)
    cfg = dict(source.config or {})
    api = Google(source, client)
    source.last_poll_at = now
    try:
        result = _sync(db, source, cfg, api, now, tz)
    except ConnectorError as exc:
        db.rollback()
        source = db.get(Source, source.id)
        source.last_poll_at = now
        source.last_error = str(exc)
        source.last_error_at = now
        db.commit()
        raise
    source.config = cfg
    source.last_ok_at = now
    source.last_error = None
    db.commit()
    result["api_calls"] = api.calls
    return result


def _sync(db: Session, source: Source, cfg: dict, api: Google, now: datetime, tz) -> dict:
    ch = api.channel()
    stats = ch.get("statistics") or {}
    playlist = ((ch.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    cfg["channel_title"] = (ch.get("snippet") or {}).get("title") or cfg.get("channel_title")
    cfg["subscribers"] = int(stats.get("subscriberCount") or 0)
    cfg["video_count"] = int(stats.get("videoCount") or 0)

    # Videos: the newest 50 every run, the full list once a day.
    last_full = _parse_time(cfg.get("last_full_list"))
    full = last_full is None or now - last_full >= FULL_VIDEO_LIST_EVERY
    ids = api.upload_ids(playlist, None if full else 1) if playlist else []
    items = upsert_videos(db, source, api.videos(ids))
    if full:
        cfg["last_full_list"] = now.isoformat()

    today = now.astimezone(tz).date()
    started = date.fromisoformat(cfg["channel_started"]) if cfg.get("channel_started") else today - timedelta(days=3650)
    recent_from = max(started, today - timedelta(days=RECENT_DAYS))

    # Channel totals per day: the recent days every run; the whole history once, a year per report.
    first_day = recent_from
    if not cfg.get("history_done") and not cfg.get("channel_history_done"):
        start = started
        while start <= today:
            end = min(today, date(start.year, 12, 31))
            store_channel_days(db, source, api.report(start, end, "day", sort="day"), tz)
            start = end + timedelta(days=1)
        cfg["channel_history_done"] = True
        first_day = started
    else:
        store_channel_days(db, source, api.report(recent_from, today, "day", sort="day"), tz)

    # Per-video numbers: one report per day (top videos of that day).
    video_rows = 0
    day = today
    while day >= recent_from:
        rows = api.report(day, day, "video", sort="-views", maxResults=TOP_VIDEOS_PER_DAY)
        video_rows += store_video_day(db, source, day, rows, items, tz)
        day -= timedelta(days=1)
    if not cfg.get("history_done"):
        until = date.fromisoformat(cfg["history_until"]) if cfg.get("history_until") else recent_from
        day = until - timedelta(days=1)
        done = 0
        while day >= started and done < HISTORY_DAYS_PER_RUN:
            rows = api.report(day, day, "video", sort="-views", maxResults=TOP_VIDEOS_PER_DAY)
            video_rows += store_video_day(db, source, day, rows, items, tz)
            done += 1
            day -= timedelta(days=1)
        oldest = day + timedelta(days=1)
        cfg["history_until"] = oldest.isoformat()
        first_day = min(first_day, oldest)
        if day < started:
            cfg["history_done"] = True

    db.flush()
    months_from_days(db, source, first_day, today, tz)
    rebuild_subscribers(db, source, cfg["subscribers"], today, tz)
    return {"videos": len(ids), "video_rows": video_rows, "history_until": cfg.get("history_until")}


def disconnect(db: Session, source: Source, client=None) -> None:
    """Revoke the token at Google (best effort) and forget it."""
    values = source_secrets(source)
    refresh = values.pop("refresh_token", None)
    if refresh:
        try:
            _client(client).post(REVOKE_URL, data={"token": refresh})
        except httpx.HTTPError:
            log.warning("revoking the YouTube token of source %s failed", source.id)
    source.secret_enc = encrypt_secret(json.dumps(values)) if values else None
    source.config = {k: v for k, v in (source.config or {}).items() if k == "client_id"}
    db.commit()
