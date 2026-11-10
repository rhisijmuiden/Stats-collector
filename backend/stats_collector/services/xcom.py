"""X (formerly Twitter): the X API v2 with OAuth 2.0 (PKCE) for one account.

X charges per post read (pay per use, about $0.005 per post in 2026), so this connector is careful:
  - a monthly budget (default $30) set on the source; Stats Collector counts every post and user it
    reads, estimates the cost and stops reading for the rest of the month when the budget is spent;
  - posts of the last 24 hours are read every few hours (default every 6 hours), posts of the last
    7 days once a day, and only while less than 80% of the budget is used;
  - right after connecting, up to 200 older posts are read once (about $1).

What is stored, per day:
  post     what the post gained since the day before: impressions, likes, reposts, replies, quotes,
           bookmarks, and for posts of the last 30 days link clicks and profile clicks
  account  the sum over its posts, new followers (net change of the follower count) and the
           follower count itself (gauge, worked back from the counts seen at every sync)

The access token lasts two hours; the refresh token (scope offline.access) is renewed at every sync,
and X hands out a new refresh token each time.
"""

from __future__ import annotations

import base64
import json
import logging
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
from .meta import _lifetime, _put_day, _title, _upsert_item, months_from_days, sum_posts_into_page
from .metrics import (
    X_BOOKMARKS,
    X_DAY_METRICS,
    X_FOLLOWERS,
    X_FOLLOWS,
    X_IMPRESSIONS,
    X_LIKES,
    X_LINK_CLICKS,
    X_POST_METRICS,
    X_PROFILE_CLICKS,
    X_QUOTES,
    X_REPLIES,
    X_REPOSTS,
)
from .rollup import org_timezone

log = logging.getLogger(__name__)

KINDS = ("x",)
AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
API = "https://api.x.com/2"
SCOPES = "tweet.read users.read offline.access"
DEFAULT_BUDGET = 30.0  # US dollars per month
DEFAULT_PRICE = 0.005  # per post read
USER_PRICE = 0.01  # per user read (the account itself)
DEFAULT_EVERY_HOURS = 6
DEEP_SHARE = 0.8  # the daily 7-day refresh only runs below this share of the budget
HISTORY_POSTS = 200
FRESH = timedelta(hours=24)
WEEK = timedelta(days=7)
PRIVATE_DAYS = 30  # X gives link and profile clicks for posts of the last 30 days only
FIELDS = "created_at,public_metrics,non_public_metrics,entities,attachments,referenced_tweets"
SETTINGS = ("client_id", "budget_usd", "price_per_post", "every_hours")


# ----------------------------------------------------------------------------- HTTP and money


def _client(client: httpx.Client | None = None) -> httpx.Client:
    return client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), headers={"User-Agent": "StatsCollector/1"})


def _check(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code == 401:
        raise ConnectorError("x_reconnect")
    if resp.status_code == 429:
        raise ConnectorError("x_rate_limit")
    if resp.status_code == 402:
        raise ConnectorError("x_payment_required")
    if resp.status_code == 403:
        raise ConnectorError(f"x_permission: {str((data or {}).get('detail') or '')[:200]}")
    if resp.status_code >= 400:
        detail = (data or {}).get("error_description") or (data or {}).get("detail") or resp.status_code
        raise ConnectorError(f"x_failed: {str(detail)[:200]}")
    return data if isinstance(data, dict) else {}


def month_key(now: datetime) -> str:
    return now.strftime("%Y-%m")


def spent(cfg: dict, now: datetime) -> float:
    """Estimated spend this month (US dollars)."""
    usage = cfg.get("usage") or {}
    return float(usage.get("usd", 0)) if usage.get("month") == month_key(now) else 0.0


def budget(cfg: dict) -> float:
    return float(cfg.get("budget_usd") or DEFAULT_BUDGET)


class Api:
    """X API client for one account that counts what it reads."""

    def __init__(self, token: str, cfg: dict, now: datetime, client: httpx.Client | None = None):
        self.token = token
        self.cfg = cfg
        self.now = now
        self.http = _client(client)
        self.price = float(cfg.get("price_per_post") or DEFAULT_PRICE)

    def _charge(self, posts: int = 0, users: int = 0) -> None:
        usage = self.cfg.get("usage") or {}
        if usage.get("month") != month_key(self.now):
            usage = {"month": month_key(self.now), "usd": 0.0, "posts": 0, "users": 0}
        usage["posts"] = int(usage.get("posts", 0)) + posts
        usage["users"] = int(usage.get("users", 0)) + users
        usage["usd"] = round(float(usage.get("usd", 0)) + posts * self.price + users * USER_PRICE, 4)
        self.cfg["usage"] = usage

    def left(self) -> float:
        return budget(self.cfg) - spent(self.cfg, self.now)

    def get(self, path: str, params: dict | None = None) -> dict:
        if self.left() <= 0:
            raise ConnectorError("x_budget_reached")
        try:
            resp = self.http.get(f"{API}/{path}", params=params, headers={"Authorization": f"Bearer {self.token}"})
        except httpx.HTTPError as exc:
            raise ConnectorError(f"unreachable: {exc.__class__.__name__}") from exc
        data = _check(resp)
        rows = data.get("data")
        if isinstance(rows, list):
            self._charge(posts=len(rows))
        elif isinstance(rows, dict):
            self._charge(users=1)
        return data


# ----------------------------------------------------------------------------- connecting


def authorize_url(cfg: dict, redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": cfg.get("client_id", ""),
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _basic(client_id: str, secret: str) -> dict:
    raw = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def _token(client_id: str, secret: str, data: dict, client=None) -> dict:
    try:
        resp = _client(client).post(TOKEN_URL, data={**data, "client_id": client_id}, headers=_basic(client_id, secret))
    except httpx.HTTPError as exc:
        raise ConnectorError("x_token_failed") from exc
    try:
        out = _check(resp)
    except ConnectorError as exc:
        raise ConnectorError(f"x_token_failed: {exc}") from exc
    if not out.get("access_token"):
        raise ConnectorError("x_token_failed")
    return out


def exchange_code(cfg: dict, secret: str, code: str, redirect_uri: str, verifier: str, client=None) -> dict:
    return _token(
        cfg.get("client_id", ""),
        secret,
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier},
        client,
    )


def _store_tokens(source: Source, values: dict, tokens: dict, now: datetime) -> str:
    values["access_token"] = tokens["access_token"]
    if tokens.get("refresh_token"):
        values["refresh_token"] = tokens["refresh_token"]
    values["expires_at"] = (now + timedelta(seconds=int(tokens.get("expires_in") or 7200) - 120)).isoformat()
    source.secret_enc = encrypt_secret(json.dumps(values))
    return values["access_token"]


def connect(db: Session, source: Source, tokens: dict, now: datetime | None = None, client=None) -> dict:
    now = now or utcnow()
    values = source_secrets(source)
    token = _store_tokens(source, values, tokens, now)
    cfg = dict(source.config or {})
    me = Api(token, cfg, now, client).get("users/me", {"user.fields": "public_metrics,username,name"})["data"]
    keep = {k: v for k, v in cfg.items() if k in SETTINGS or k == "usage"}
    if cfg.get("account_id") == me.get("id"):
        keep = cfg  # the same account again: keep how far the history came
    source.config = {
        **keep,
        "account_id": me.get("id"),
        "account_name": f"@{me.get('username')}",
        "account_url": f"https://x.com/{me.get('username')}",
        "followers": int((me.get("public_metrics") or {}).get("followers_count") or 0),
    }
    source.last_error = None
    db.commit()
    return {"account_id": me.get("id"), "name": source.config["account_name"]}


def disconnect(db: Session, source: Source) -> None:
    values = {k: v for k, v in source_secrets(source).items() if k == "client_secret"}
    source.secret_enc = encrypt_secret(json.dumps(values)) if values else None
    source.config = {k: v for k, v in (source.config or {}).items() if k in SETTINGS or k == "usage"}
    db.commit()


def _access_token(source: Source, now: datetime, client=None) -> str:
    values = source_secrets(source)
    if not values.get("refresh_token"):
        raise ConnectorError("x_reconnect")
    at = values.get("expires_at")
    if values.get("access_token") and at and datetime.fromisoformat(at) > now:
        return values["access_token"]
    cfg = source.config or {}
    try:
        tokens = _token(
            cfg.get("client_id", ""),
            values.get("client_secret", ""),
            {"grant_type": "refresh_token", "refresh_token": values["refresh_token"]},
            client,
        )
    except ConnectorError as exc:
        if "invalid_request" in str(exc) or "invalid_grant" in str(exc) or "x_reconnect" in str(exc):
            raise ConnectorError("x_reconnect") from exc
        raise
    return _store_tokens(source, values, tokens, now)


# ----------------------------------------------------------------------------- sync


def is_due(source: Source, now: datetime) -> bool:
    cfg = source.config or {}
    if not cfg.get("account_id") or cfg.get("demo"):
        return False
    if spent(cfg, now) >= budget(cfg):
        return False
    last = source.last_poll_at
    if last is None:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    every = timedelta(hours=max(1, min(24, int(cfg.get("every_hours") or DEFAULT_EVERY_HOURS))))
    return now - last >= every - timedelta(minutes=5)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _timeline(api: Api, user_id: str, start: datetime | None, limit: int, until_id: str | None = None):
    """Own posts (no reposts, no replies), newest first; at most `limit` posts are read."""
    params: dict[str, Any] = {"max_results": 100, "tweet.fields": FIELDS, "exclude": "retweets,replies"}
    if start:
        params["start_time"] = _iso(start)
    if until_id:
        params["until_id"] = until_id
    read = 0
    while read < limit:
        params["max_results"] = max(5, min(100, limit - read))
        data = api.get(f"users/{user_id}/tweets", params)
        rows = data.get("data") or []
        read += len(rows)
        yield from rows
        token = (data.get("meta") or {}).get("next_token")
        if not token or not rows:
            return
        params["pagination_token"] = token


def _links(row: dict) -> list[str]:
    urls = []
    for u in (row.get("entities") or {}).get("urls") or []:
        url = u.get("unwound_url") or u.get("expanded_url")
        if isinstance(url, str) and url.startswith(("http://", "https://")) and "x.com/" not in url:
            urls.append(url)
    return list(dict.fromkeys(urls))[:20]


def _totals(row: dict) -> dict[str, float]:
    pub = row.get("public_metrics") or {}
    private = row.get("non_public_metrics") or {}
    out = {
        X_IMPRESSIONS: float(private.get("impression_count") or pub.get("impression_count") or 0),
        X_LIKES: float(pub.get("like_count") or 0),
        X_REPOSTS: float(pub.get("retweet_count") or 0),
        X_REPLIES: float(pub.get("reply_count") or 0),
        X_QUOTES: float(pub.get("quote_count") or 0),
        X_BOOKMARKS: float(pub.get("bookmark_count") or 0),
    }
    if private:
        out[X_LINK_CLICKS] = float(private.get("url_link_clicks") or 0)
        out[X_PROFILE_CLICKS] = float(private.get("user_profile_clicks") or 0)
    return out


def _store_post(db: Session, source: Source, row: dict, username: str, today: date, tz) -> set[date]:
    published = _time(row.get("created_at"))
    item = _upsert_item(db, source, str(row["id"]), "post")
    item.title = _title(row.get("text"), "(no text)")
    item.url = f"https://x.com/{username}/status/{row['id']}"
    item.published_at = published or item.published_at
    item.meta = {**(item.meta or {}), "links": _links(row)}
    db.flush()
    pub = published.astimezone(tz).date() if published else None
    days = _lifetime(item, _totals(row), pub, today)
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
        api = Api(_access_token(source, now, client), cfg, now, client)
        db.commit()  # X hands out a new refresh token each time: keep it even when the sync fails
        me = api.get("users/me", {"user.fields": "public_metrics,username"})["data"]
        username = me.get("username") or cfg.get("account_name", "@").lstrip("@")
        cfg["account_name"] = f"@{username}"
        cfg["account_url"] = f"https://x.com/{username}"
        user_id = cfg["account_id"]

        changed: set[date] = set()
        n = 0
        deep = cfg.get("deep_day") != today.isoformat() and spent(cfg, now) < budget(cfg) * DEEP_SHARE
        start = now - (WEEK if deep else FRESH)
        oldest_id = None
        for row in _timeline(api, user_id, start, 800):
            changed |= _store_post(db, source, row, username, today, tz)
            oldest_id = row["id"]
            n += 1
        if deep:
            cfg["deep_day"] = today.isoformat()
        if not cfg.get("history_done") and api.left() > HISTORY_POSTS * api.price * 2:
            # Once: older posts, so Content and Editors have something to show from the start.
            for row in _timeline(api, user_id, None, HISTORY_POSTS, until_id=cfg.get("history_until") or oldest_id):
                changed |= _store_post(db, source, row, username, today, tz)
                n += 1
            cfg["history_done"] = True
        db.flush()
        if changed:
            sum_posts_into_page(db, source, changed, X_POST_METRICS, tz)

        followers = int((me.get("public_metrics") or {}).get("followers_count") or 0)
        cfg["followers"] = followers
        counts = log_count(cfg, today, followers)
        earlier = [d for d in counts if d < today]
        if earlier:
            _put_day(db, source, None, day_bucket(today, tz), {X_FOLLOWS: counts[today] - counts[max(earlier)]})
        rebuild_gauge(db, source, X_FOLLOWERS, X_FOLLOWS, None, counts, today, tz)
        months_from_days(db, source, min([*changed, today]), today, X_DAY_METRICS, tz)
    except ConnectorError as exc:
        db.rollback()
        fresh = db.get(Source, source.id)
        fresh.last_poll_at = now
        fresh.last_error = str(exc)
        fresh.last_error_at = now
        if "usage" in cfg:  # what was read is paid for, also when the sync failed
            fresh.config = {**(fresh.config or {}), "usage": cfg["usage"]}
        db.commit()
        raise
    source.config = cfg
    source.last_ok_at = now
    source.last_error = None
    db.commit()
    return {"posts": n, "days": len(changed), "spent_usd": spent(cfg, now)}
