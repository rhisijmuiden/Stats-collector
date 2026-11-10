"""Threads: the Threads API of the Meta app (use case "Access the Threads API").

Connecting: the admin signs in on threads.net with the Threads account; the code is exchanged for a
long-lived token (60 days) that is refreshed every week, so it never runs out while syncs run.

What is stored, per day:
  account  th_views (from the account insights), the sums of what its posts gained (likes,
           replies, reposts, quotes, shares), new followers (net change of the follower count)
           and the follower count itself (gauge, worked back from the counts seen at every sync)
  post     what the post gained since the day before: views, likes, replies, reposts, quotes,
           shares (first sight: its whole total on the day it came out)

Threads has no reach. The account insights start on 13 April 2024; history goes back two years at
most. Posts of the last 7 days are read every hour, posts of the last 30 days once a day.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from ..connectors import ConnectorError
from ..models import Source, utcnow
from ..security import encrypt_secret
from .collect import source_secrets
from .followers import day_bucket, log_count, rebuild_gauge
from .links import extract_urls
from .meta import _insights_day, _lifetime, _put_day, _title, _upsert_item, months_from_days, sum_posts_into_page
from .metrics import (
    TH_DAY_METRICS,
    TH_FOLLOWERS,
    TH_FOLLOWS,
    TH_LIKES,
    TH_POST_METRICS,
    TH_QUOTES,
    TH_REPLIES,
    TH_REPOSTS,
    TH_SHARES,
    TH_VIEWS,
)
from .rollup import org_timezone

log = logging.getLogger(__name__)

KINDS = ("threads",)
AUTH_URL = "https://threads.net/oauth/authorize"
API = "https://graph.threads.net"
VERSION = "v1.0"
SCOPES = "threads_basic,threads_manage_insights"
SYNC_EVERY = timedelta(hours=1)
REFRESH_TOKEN_EVERY = timedelta(days=7)
FIRST_DAY = date(2024, 4, 13)  # the oldest day Threads keeps insights for
HISTORY_DAYS = 730
WINDOW = 90  # days per account insights request
WINDOWS_PER_RUN = 4
RECENT_DAYS = 3
HOURLY_POST_DAYS = 7
DAILY_POST_DAYS = 30
PAGE_SIZE = 50
PAGES_PER_RUN = 5
POST_METRICS = {
    TH_VIEWS: "views",
    TH_LIKES: "likes",
    TH_REPLIES: "replies",
    TH_REPOSTS: "reposts",
    TH_QUOTES: "quotes",
    TH_SHARES: "shares",
}
SUMMED = tuple(m for m in TH_POST_METRICS if m != TH_VIEWS)  # account views come from the insights
SETTINGS = ("client_id",)


# ----------------------------------------------------------------------------- HTTP


def _client(client: httpx.Client | None = None) -> httpx.Client:
    return client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), headers={"User-Agent": "StatsCollector/1"})


def _check(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    err = data.get("error") if isinstance(data, dict) else None
    if resp.status_code < 400 and not err:
        return data if isinstance(data, dict) else {}
    err = err if isinstance(err, dict) else {}
    code = err.get("code")
    message = str(err.get("message") or "")[:200]
    if code == 190 or resp.status_code == 401:
        raise ConnectorError(f"threads_reconnect: {message}")
    if code in (4, 17, 32, 613) or resp.status_code == 429:
        raise ConnectorError("threads_rate_limit")
    if code == 10 or (isinstance(code, int) and 200 <= code < 300):
        raise ConnectorError(f"threads_permission: {message}")
    raise ConnectorError(f"threads_failed: {message or resp.status_code}")


class Api:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.token = token
        self.http = _client(client)
        self.calls = 0

    def get(self, path: str, params: dict | None = None) -> dict:
        self.calls += 1
        try:
            resp = self.http.get(f"{API}/{VERSION}/{path}", params={**(params or {}), "access_token": self.token})
        except httpx.HTTPError as exc:
            raise ConnectorError(f"unreachable: {exc.__class__.__name__}") from exc
        return _check(resp)


# ----------------------------------------------------------------------------- connecting


def authorize_url(cfg: dict, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": cfg.get("client_id", ""),
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "response_type": "code",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(cfg: dict, app_secret: str, code: str, redirect_uri: str, client=None) -> str:
    """Code -> short-lived token -> long-lived token (60 days)."""
    http = _client(client)
    try:
        short = _check(
            http.post(
                f"{API}/oauth/access_token",
                data={
                    "client_id": cfg.get("client_id", ""),
                    "client_secret": app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code": code.removesuffix("#_"),
                },
            )
        )
        long = _check(
            http.get(
                f"{API}/access_token",
                params={
                    "grant_type": "th_exchange_token",
                    "client_secret": app_secret,
                    "access_token": short.get("access_token", ""),
                },
            )
        )
    except httpx.HTTPError as exc:
        raise ConnectorError("threads_token_failed") from exc
    except ConnectorError as exc:
        raise ConnectorError(f"threads_token_failed: {exc}") from exc
    if not long.get("access_token"):
        raise ConnectorError("threads_token_failed")
    return long["access_token"]


def connect(db: Session, source: Source, token: str, now: datetime | None = None, client=None) -> dict:
    me = Api(token, client).get("me", {"fields": "id,username,name"})
    if not me.get("id"):
        raise ConnectorError("threads_failed")
    values = source_secrets(source)
    values.update(token=token, token_at=(now or utcnow()).isoformat())
    source.secret_enc = encrypt_secret(json.dumps(values))
    keep = {k: v for k, v in (source.config or {}).items() if k in SETTINGS}
    if (source.config or {}).get("account_id") == me["id"]:
        keep = dict(source.config or {})  # the same account again: keep how far the history came
    source.config = {
        **keep,
        "account_id": me["id"],
        "account_name": f"@{me.get('username')}",
        "account_url": f"https://www.threads.net/@{me.get('username')}",
    }
    source.last_error = None
    db.commit()
    return {"account_id": me["id"], "name": source.config["account_name"]}


def disconnect(db: Session, source: Source) -> None:
    values = {k: v for k, v in source_secrets(source).items() if k == "client_secret"}
    source.secret_enc = encrypt_secret(json.dumps(values)) if values else None
    source.config = {k: v for k, v in (source.config or {}).items() if k in SETTINGS}
    db.commit()


def _refresh_token(source: Source, values: dict, now: datetime, client=None) -> str:
    """Threads tokens last 60 days; a refresh gives 60 days again (allowed after 24 hours)."""
    token = values.get("token", "")
    at = values.get("token_at")
    if at and now - datetime.fromisoformat(at) < REFRESH_TOKEN_EVERY:
        return token
    try:
        resp = _client(client).get(
            f"{API}/refresh_access_token", params={"grant_type": "th_refresh_token", "access_token": token}
        )
    except httpx.HTTPError:
        return token  # try again next time; the token is still valid for weeks
    data = _check(resp)
    if data.get("access_token"):
        values.update(token=data["access_token"], token_at=now.isoformat())
        source.secret_enc = encrypt_secret(json.dumps(values))
    return values.get("token", token)


# ----------------------------------------------------------------------------- sync


def is_due(source: Source, now: datetime) -> bool:
    cfg = source.config or {}
    if not cfg.get("account_id") or cfg.get("demo"):
        return False
    if not (cfg.get("posts_done") and cfg.get("days_done")):
        return True
    last = source.last_poll_at
    if last is None:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    return now - last >= SYNC_EVERY


def _unix(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), UTC).timestamp())


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _account_views(api: Api, user_id: str, first: date, last: date) -> dict[date, float]:
    data = api.get(
        f"{user_id}/threads_insights",
        {"metric": "views", "since": _unix(first), "until": _unix(last + timedelta(days=1))},
    )
    out: dict[date, float] = {}
    for series in data.get("data") or []:
        if series.get("name") != "views":
            continue
        for v in series.get("values") or []:
            day = _insights_day(v.get("end_time"))
            if day and first <= day <= last:
                out[day] = float(v.get("value") or 0)
    return out


def _followers(api: Api, user_id: str) -> int | None:
    data = api.get(f"{user_id}/threads_insights", {"metric": "followers_count"})
    for series in data.get("data") or []:
        if series.get("name") == "followers_count":
            return int((series.get("total_value") or {}).get("value") or 0)
    return None


def _history_windows(cfg: dict, today: date) -> list[tuple[date, date]]:
    """The next account insights windows to fetch, going back from where the import got to."""
    oldest = max(FIRST_DAY, today - timedelta(days=HISTORY_DAYS - 1))
    until = date.fromisoformat(cfg["days_until"]) if cfg.get("days_until") else today - timedelta(days=RECENT_DAYS)
    out = []
    while until > oldest and len(out) < WINDOWS_PER_RUN:
        start = max(oldest, until - timedelta(days=WINDOW))
        out.append((start, until - timedelta(days=1)))
        until = start
    cfg["days_until"] = until.isoformat()
    cfg["days_done"] = until <= oldest
    return out


def _posts(api: Api, cfg: dict, user_id: str, today: date) -> Iterator[dict]:
    """Recent posts (7 days every hour, 30 days once a day), plus older ones until two years are in."""
    fields = "id,text,permalink,timestamp,media_type,media_product_type,thumbnail_url,media_url,is_quote_post"
    deep = cfg.get("deep_day") != today.isoformat()
    since = today - timedelta(days=DAILY_POST_DAYS if deep else HOURLY_POST_DAYS)
    seen: set[str] = set()
    params: dict[str, Any] = {"fields": fields, "limit": PAGE_SIZE, "since": _unix(since)}
    for _ in range(PAGES_PER_RUN * 2):
        data = api.get(f"{user_id}/threads", params)
        for row in data.get("data") or []:
            seen.add(row["id"])
            yield row
        after = ((data.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not (data.get("paging") or {}).get("next"):
            break
        params["after"] = after
    if deep:
        cfg["deep_day"] = today.isoformat()
    if cfg.get("posts_done"):
        return
    oldest = max(FIRST_DAY, today - timedelta(days=HISTORY_DAYS))
    params = {"fields": fields, "limit": PAGE_SIZE, "since": _unix(oldest)}
    if cfg.get("posts_after"):
        params["after"] = cfg["posts_after"]
    for _ in range(PAGES_PER_RUN):
        data = api.get(f"{user_id}/threads", params)
        for row in data.get("data") or []:
            if row["id"] not in seen:
                yield row
        after = ((data.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not (data.get("paging") or {}).get("next"):
            cfg["posts_done"] = True
            cfg.pop("posts_after", None)
            return
        cfg["posts_after"] = params["after"] = after


def _post_totals(api: Api, post_id: str) -> dict[str, float]:
    try:
        data = api.get(f"{post_id}/insights", {"metric": ",".join(POST_METRICS.values())})
    except ConnectorError as exc:
        if str(exc).startswith(("threads_reconnect", "threads_rate_limit")):
            raise
        return {}  # e.g. a post that was removed
    by_name = {v: k for k, v in POST_METRICS.items()}
    out: dict[str, float] = {}
    for series in data.get("data") or []:
        key = by_name.get(series.get("name"))
        values = series.get("values") or []
        if key and values:
            out[key] = float(values[-1].get("value") or 0)
        elif key and "total_value" in series:
            out[key] = float((series.get("total_value") or {}).get("value") or 0)
    return out


def _store_post(db: Session, source: Source, row: dict, totals: dict[str, float], today: date, tz) -> set[date]:
    published = _time(row.get("timestamp"))
    item = _upsert_item(db, source, str(row["id"]), "post")
    item.title = _title(row.get("text"), "(no text)")
    item.url = row.get("permalink")
    item.published_at = published or item.published_at
    item.meta = {
        **(item.meta or {}),
        "thumbnail": row.get("thumbnail_url") or (row.get("media_url") if row.get("media_type") == "IMAGE" else None),
        "media_type": row.get("media_type"),
        "links": extract_urls(row.get("text"))[:20],
    }
    db.flush()
    pub = published.astimezone(tz).date() if published else None
    days = _lifetime(item, totals, pub, today)
    for day, values in days.items():
        _put_day(db, source, item.id, day_bucket(day, tz), values)
    return set(days)


def sync(db: Session, source: Source, now: datetime | None = None, client=None) -> dict:
    if (source.config or {}).get("demo"):
        return {"demo": True}
    now = now or utcnow()
    tz = org_timezone(db)
    today = now.astimezone(tz).date()
    cfg = dict(source.config or {})
    source.last_poll_at = now
    try:
        values = source_secrets(source)
        if not values.get("token"):
            raise ConnectorError("threads_reconnect: no token")
        api = Api(_refresh_token(source, values, now, client), client)
        user_id = cfg["account_id"]
        me = api.get("me", {"fields": "id,username"})
        if me.get("username"):
            cfg["account_name"] = f"@{me['username']}"
            cfg["account_url"] = f"https://www.threads.net/@{me['username']}"

        # Views per day for the account: the last days every run, older windows until two years are in.
        windows = [(max(FIRST_DAY, today - timedelta(days=RECENT_DAYS)), today), *_history_windows(cfg, today)]
        for first, last in windows:
            for day, views in _account_views(api, user_id, first, last).items():
                _put_day(db, source, None, day_bucket(day, tz), {TH_VIEWS: views})

        changed: set[date] = set()
        n = 0
        for row in _posts(api, cfg, user_id, today):
            if row.get("media_type") == "REPOST_FACADE":
                continue  # a repost of someone else's post
            changed |= _store_post(db, source, row, _post_totals(api, row["id"]), today, tz)
            n += 1
        db.flush()
        if changed:
            sum_posts_into_page(db, source, changed, SUMMED, tz)

        followers = _followers(api, user_id)
        if followers is not None:
            cfg["followers"] = followers
            counts = log_count(cfg, today, followers)
            earlier = [d for d in counts if d < today]
            if earlier:
                delta = counts[today] - counts[max(earlier)]
                _put_day(db, source, None, day_bucket(today, tz), {TH_FOLLOWS: delta})
            rebuild_gauge(db, source, TH_FOLLOWERS, TH_FOLLOWS, None, counts, today, tz)
        first_day = min([*changed, *(w[0] for w in windows), today])
        months_from_days(db, source, first_day, today, TH_DAY_METRICS, tz)
        cfg["history_done"] = bool(cfg.get("posts_done") and cfg.get("days_done"))
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
    return {"posts": n, "days": len(changed), "api_calls": api.calls}
