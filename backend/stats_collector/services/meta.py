"""Facebook Pages and Instagram professional accounts through Meta's Graph API.

One Meta app (App ID and secret, entered per source) and one consent screen ("Facebook Login for
Business") serve both platforms: a `facebook` source measures one Page, an `instagram` source one
Instagram account that is linked to a Page. Both keep the Page access token, which does not expire
as long as the administrator who connected it keeps access.

What is stored, per day:
  facebook page   fb_views, fb_reach, fb_engagements, fb_video_views, fb_follows, fb_unfollows
                  (Page Insights, a real series per day, up to two years back)
                  fb_reactions, fb_comments, fb_shares, fb_clicks (sum of the posts below)
                  fb_followers (gauge, see services/followers.py)
  facebook post   fb_views, fb_reach, fb_clicks, fb_reactions, fb_comments, fb_shares
  instagram       ig_views, ig_reach, ig_likes, ig_comments, ig_shares, ig_saves, ig_profile_views
                  (account insights, one request per day), ig_follows (last 30 days only),
                  ig_followers (gauge)
  instagram post  ig_views, ig_reach, ig_likes, ig_comments, ig_shares, ig_saves

Meta reports posts only as lifetime totals. Each sync stores what a post gained since the start of
the day; a post seen for the first time gets its whole total on the day it was published.

Meta renames insights metrics from one API version to the next. Every metric therefore has a list
of names to try (newest first), the administrator can put their own name in front of it, and the
names that work are remembered per Graph API version.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..connectors import ConnectorError
from ..models import ContentItem, MetricPoint, Source, utcnow
from ..security import encrypt_secret
from .collect import source_secrets
from .followers import day_bucket, log_count, rebuild_gauge
from .links import extract_urls
from .metrics import (
    FB_CLICKS,
    FB_COMMENTS,
    FB_DAY_METRICS,
    FB_ENGAGEMENTS,
    FB_FOLLOWERS,
    FB_FOLLOWS,
    FB_REACH,
    FB_REACTIONS,
    FB_SHARES,
    FB_UNFOLLOWS,
    FB_VIDEO_VIEWS,
    FB_VIEWS,
    IG_COMMENTS,
    IG_DAY_METRICS,
    IG_FOLLOWERS,
    IG_FOLLOWS,
    IG_LIKES,
    IG_PROFILE_VIEWS,
    IG_REACH,
    IG_SAVES,
    IG_SHARES,
    IG_VIEWS,
)
from .rollup import _sum_from, local_month_start, next_local_month, org_timezone

log = logging.getLogger(__name__)

KINDS = ("facebook", "instagram")
GRAPH_VERSION = "v23.0"
DIALOG_URL = "https://www.facebook.com/{v}/dialog/oauth"
GRAPH_URL = "https://graph.facebook.com/{v}"
PERMISSIONS = (
    "pages_show_list",
    "pages_read_engagement",
    "read_insights",
    "business_management",
    "instagram_basic",
    "instagram_manage_insights",
)

# Our metric -> Graph API names to try, newest first.
FB_PAGE_METRICS = {
    FB_VIEWS: ["page_media_view", "page_impressions"],
    FB_REACH: ["page_total_media_view_unique", "page_impressions_unique"],
    FB_ENGAGEMENTS: ["page_post_engagements"],
    FB_VIDEO_VIEWS: ["page_video_views"],
    FB_FOLLOWS: ["page_daily_follows_unique", "page_fan_adds_unique"],
    FB_UNFOLLOWS: ["page_daily_unfollows_unique", "page_fan_removes_unique"],
}
FB_POST_METRICS = {
    FB_VIEWS: ["post_media_view", "post_impressions"],
    FB_REACH: ["post_total_media_view_unique", "post_impressions_unique"],
    FB_CLICKS: ["post_clicks"],
    "reactions_by_type": ["post_reactions_by_type_total"],
}
IG_ACCOUNT_METRICS = {
    IG_VIEWS: ["views", "impressions"],
    IG_REACH: ["reach"],
    IG_LIKES: ["likes"],
    IG_COMMENTS: ["comments"],
    IG_SHARES: ["shares"],
    IG_SAVES: ["saves"],
    IG_PROFILE_VIEWS: ["profile_views"],
}
IG_MEDIA_METRICS = {
    IG_VIEWS: ["views", "impressions", "plays"],
    IG_REACH: ["reach"],
    IG_SHARES: ["shares"],
    IG_SAVES: ["saved"],
}
ALL_METRIC_KEYS = sorted(
    {*FB_PAGE_METRICS, *FB_POST_METRICS, *IG_ACCOUNT_METRICS, *IG_MEDIA_METRICS} - {"reactions_by_type"}
)
FB_FROM_POSTS = (FB_REACTIONS, FB_COMMENTS, FB_SHARES, FB_CLICKS)  # page totals = sum of its posts

SYNC_EVERY = timedelta(hours=1)
RECENT_DAYS = 3  # page days re-read every sync
POST_REFRESH_DAYS = 30  # posts whose totals are read again every sync
FB_HISTORY_DAYS = 730  # Page Insights keep two years
IG_HISTORY_DAYS = 90
IG_DAYS_PER_RUN = 30
POST_PAGES_PER_RUN = 20
PAGE_SIZE = 50
INSIGHTS_SPAN = 90  # days per Page Insights request (Meta allows 93)
BATCH = 50


class InvalidMetric(Exception):
    """Meta does not know a metric name (any more)."""


# ----------------------------------------------------------------------------- HTTP


def _client(client: httpx.Client | None = None) -> httpx.Client:
    return client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), headers={"User-Agent": "StatsCollector/1"})


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {}


def _check(status: int, data: Any) -> Any:
    """Raise the matching error for a Graph API error response."""
    err = data.get("error") if isinstance(data, dict) else None
    if status < 400 and not err:
        return data
    err = err if isinstance(err, dict) else {}
    code = err.get("code")
    message = str(err.get("message") or "")[:200]
    if code == 190 or err.get("type") == "OAuthException" and code in (102, 463, 467):
        raise ConnectorError(f"meta_reconnect: {message}")
    if code in (4, 17, 32, 613) or code in range(80001, 80015):
        raise ConnectorError("meta_rate_limit")
    if code == 100 and "metric" in message.lower():
        raise InvalidMetric(message)
    if code == 10 or (isinstance(code, int) and 200 <= code < 300):
        raise ConnectorError(f"meta_permission: {message}")
    raise ConnectorError(f"meta_failed: {message or status}")


def graph_version(cfg: dict) -> str:
    v = str((cfg or {}).get("graph_version") or GRAPH_VERSION).strip()
    return v if v.startswith("v") else f"v{v}"


def authorize_url(cfg: dict, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": cfg.get("client_id", ""),
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }
    if cfg.get("config_id"):  # Facebook Login for Business: the permissions live in the configuration
        params["config_id"] = cfg["config_id"]
        params["override_default_response_type"] = "true"
    else:
        params["scope"] = ",".join(PERMISSIONS)
    return f"{DIALOG_URL.format(v=graph_version(cfg))}?{urlencode(params)}"


def exchange_code(cfg: dict, app_secret: str, code: str, redirect_uri: str, client=None) -> str:
    """Code -> short-lived user token -> long-lived user token."""
    http = _client(client)
    base = GRAPH_URL.format(v=graph_version(cfg))
    try:
        short = _check_resp(
            http.get(
                f"{base}/oauth/access_token",
                params={
                    "client_id": cfg.get("client_id", ""),
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
        )
        long = _check_resp(
            http.get(
                f"{base}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": cfg.get("client_id", ""),
                    "client_secret": app_secret,
                    "fb_exchange_token": short.get("access_token", ""),
                },
            )
        )
    except httpx.HTTPError as exc:
        raise ConnectorError("meta_token_failed") from exc
    except ConnectorError as exc:
        raise ConnectorError(f"meta_token_failed: {exc}") from exc
    if not long.get("access_token"):
        raise ConnectorError("meta_token_failed")
    return long["access_token"]


def _check_resp(resp: httpx.Response) -> dict:
    data = _json(resp)
    _check(resp.status_code, data)
    return data if isinstance(data, dict) else {}


def proof(app_secret: str, token: str) -> str:
    return hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


class Graph:
    """Graph API client for one Page (or the Instagram account linked to it)."""

    def __init__(self, source: Source, client: httpx.Client | None = None, token: str | None = None):
        self.source = source
        self.secrets = source_secrets(source)
        self.version = graph_version(source.config or {})
        self.base = GRAPH_URL.format(v=self.version)
        self.http = _client(client)
        self.token = token or self.secrets.get("page_token")
        self.calls = 0

    def _auth(self) -> dict:
        if not self.token:
            raise ConnectorError("meta_not_connected")
        params = {"access_token": self.token}
        if self.secrets.get("client_secret"):
            params["appsecret_proof"] = proof(self.secrets["client_secret"], self.token)
        return params

    def _send(self, method: str, url: str, **kw) -> Any:
        try:
            resp = self.http.request(method, url, **kw)
        except httpx.TimeoutException as exc:
            raise ConnectorError("timeout") from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(f"connection_failed: {exc}") from exc
        self.calls += 1
        return _check(resp.status_code, _json(resp))

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._send("GET", f"{self.base}/{path.lstrip('/')}", params={**(params or {}), **self._auth()})

    def pages(self, path: str, params: dict, max_pages: int) -> Iterator[tuple[list[dict], str | None]]:
        """Yield (rows, cursor after them) page by page."""
        params = dict(params)
        for _ in range(max_pages):
            data = self.get(path, params)
            after = ((data.get("paging") or {}).get("cursors") or {}).get("after")
            has_next = bool((data.get("paging") or {}).get("next"))
            yield data.get("data") or [], after if has_next else None
            if not has_next or not after:
                return
            params["after"] = after

    def batch(self, urls: list[str]) -> list[tuple[int, Any]]:
        """Several GET requests in one call; returns (status, body) per request, in order."""
        out: list[tuple[int, Any]] = []
        for i in range(0, len(urls), BATCH):
            chunk = urls[i : i + BATCH]
            data = self._send(
                "POST",
                f"{self.base}/",
                data={**self._auth(), "batch": json.dumps([{"method": "GET", "relative_url": u} for u in chunk])},
            )
            for part in data if isinstance(data, list) else [None] * len(chunk):
                if not isinstance(part, dict):
                    out.append((0, {}))
                    continue
                try:
                    body = json.loads(part.get("body") or "{}")
                except ValueError:
                    body = {}
                out.append((int(part.get("code") or 0), body))
        return out


def accounts(user_token: str, cfg: dict, app_secret: str, client=None) -> list[dict]:
    """The Pages the administrator manages, each with its token and linked Instagram account."""
    fake = Source(kind="facebook", config=cfg)
    api = Graph(fake, client, token=user_token)
    api.secrets = {"client_secret": app_secret}
    fields = "id,name,link,access_token,followers_count,instagram_business_account{id,username,name,followers_count}"
    rows: list[dict] = []
    for page, _ in api.pages("me/accounts", {"fields": fields, "limit": 100}, 10):
        rows += page
    return rows


def candidates(kind: str, pages: list[dict]) -> list[dict]:
    out = []
    for p in pages:
        if not p.get("access_token"):
            continue
        if kind == "facebook":
            out.append(
                {
                    "id": str(p["id"]),
                    "name": p.get("name") or str(p["id"]),
                    "url": p.get("link") or f"https://www.facebook.com/{p['id']}",
                    "token": p["access_token"],
                }
            )
        elif (ig := p.get("instagram_business_account")) and ig.get("id"):
            username = ig.get("username") or ig.get("name") or ig["id"]
            out.append(
                {
                    "id": str(ig["id"]),
                    "name": f"@{username}",
                    "page": p.get("name"),
                    "url": f"https://www.instagram.com/{username}/",
                    "token": p["access_token"],
                }
            )
    return out


# ----------------------------------------------------------------------------- metric names


def _probe(api: Graph, kind: str, target: str, obj_id: str, name: str, today: date) -> None:
    if target == "page":
        since = datetime.combine(today - timedelta(days=2), datetime.min.time(), UTC)
        params = {
            "metric": name,
            "period": "day",
            "since": int(since.timestamp()),
            "until": int(since.timestamp()) + 86400,
        }
        if kind == "instagram":
            params["metric_type"] = "total_value"
        api.get(f"{obj_id}/insights", params)
    else:
        api.get(f"{obj_id}/insights", {"metric": name})


def metric_names(api: Graph, cfg: dict, target: str, obj_id: str | None, today: date) -> dict[str, str]:
    """Our metric -> the Graph name that works, found once per API version and remembered."""
    kind = api.source.kind
    table = {
        ("facebook", "page"): FB_PAGE_METRICS,
        ("facebook", "post"): FB_POST_METRICS,
        ("instagram", "page"): IG_ACCOUNT_METRICS,
        ("instagram", "post"): IG_MEDIA_METRICS,
    }[(kind, target)]
    cache = (cfg.get("metric_names") or {}).get(target)
    if cache and cache.get("_v") == api.version:
        return {k: v for k, v in cache.items() if k != "_v" and v}
    if obj_id is None:
        return {k: names[0] for k, names in table.items()}  # nothing to try them on yet
    overrides = cfg.get("metric_overrides") or {}
    found: dict[str, str] = {}
    for key, names in table.items():
        tries = list(dict.fromkeys([overrides[key], *names] if overrides.get(key) else names))
        for name in tries:
            try:
                _probe(api, kind, target, obj_id, name, today)
            except InvalidMetric:
                continue
            except ConnectorError as exc:
                if str(exc).startswith(("meta_reconnect", "meta_rate_limit")):
                    raise
                continue  # e.g. not available for this kind of post
            found[key] = name
            break
    cfg["metric_names"] = {**(cfg.get("metric_names") or {}), target: {**found, "_v": api.version}}
    missing = sorted(set(cfg.get("unsupported_metrics") or []) - set(table) | {k for k in table if k not in found})
    cfg["unsupported_metrics"] = [m for m in missing if m != "reactions_by_type"]
    return found


def _forget_names(cfg: dict, target: str) -> None:
    cfg["metric_names"] = {k: v for k, v in (cfg.get("metric_names") or {}).items() if k != target}


# ----------------------------------------------------------------------------- storing


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


def _number(value: Any) -> float:
    if isinstance(value, dict):  # e.g. reactions by type
        return float(sum(v for v in value.values() if isinstance(v, int | float)))
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _insights_day(end_time: Any) -> date | None:
    """Meta labels a day by the moment it ends (midnight Pacific time, 07:00 or 08:00 UTC)."""
    end = _parse_time(end_time)
    return (end - timedelta(days=1)).date() if end else None


def store_page_series(db: Session, source: Source, data: list[dict], names: dict[str, str], tz) -> set[date]:
    """Page Insights rows (one series per metric) -> page totals per day."""
    by_name = {v: k for k, v in names.items()}
    per_day: dict[date, dict[str, float]] = {}
    for series in data:
        key = by_name.get(series.get("name"))
        if not key:
            continue
        for v in series.get("values") or []:
            day = _insights_day(v.get("end_time"))
            if day:
                per_day.setdefault(day, {})[key] = _number(v.get("value"))
    for day, values in per_day.items():
        _put_day(db, source, None, day_bucket(day, tz), {k: values.get(k, 0) for k in names})
    return set(per_day)


def _lifetime(item: ContentItem, totals: dict[str, float], published: date | None, today: date) -> dict[date, dict]:
    """What a post gained per day, from its lifetime totals now and earlier ones in item.meta."""
    meta = dict(item.meta or {})
    last = meta.get("lt")
    out: dict[date, dict] = {}
    if last is None:
        if published and published < today:
            out[published] = dict(totals)  # first sight: its whole total on the day it came out
            base = dict(totals)
        else:
            base = {}
        meta["lt_base"], meta["lt_day"] = base, today.isoformat()
    elif meta.get("lt_day") != today.isoformat():
        meta["lt_base"], meta["lt_day"] = dict(last), today.isoformat()
    base = meta.get("lt_base") or {}
    out[today] = {k: max(v - float(base.get(k, 0)), 0) for k, v in totals.items()}
    meta["lt"] = dict(totals)
    item.meta = meta
    return out


def _upsert_item(db: Session, source: Source, external_id: str, kind: str) -> ContentItem:
    item = db.execute(
        select(ContentItem).where(ContentItem.source_id == source.id, ContentItem.external_id == external_id)
    ).scalar_one_or_none()
    if item is None:
        item = ContentItem(tenant_id=source.tenant_id, source_id=source.id, kind=kind, external_id=external_id)
        db.add(item)
    return item


def _title(text: Any, fallback: str) -> str:
    line = " ".join(str(text or "").split())
    return (line[:117] + "…" if len(line) > 120 else line) or fallback


def _post_links(post: dict, fb: bool) -> list[str]:
    """Web addresses a post points to: the attached link (Facebook) and links in its text."""
    attached = []
    if fb:
        for a in (post.get("attachments") or {}).get("data") or []:
            url = a.get("unshimmed_url") or a.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                attached.append(url)
    found = extract_urls(post.get("message") if fb else post.get("caption"))
    return list(dict.fromkeys(attached + found))[:20]


def store_post(db: Session, source: Source, post: dict, totals: dict[str, float], extra: dict, today: date, tz) -> set:
    """Create or update a post and store what it gained; returns the days that changed."""
    fb = source.kind == "facebook"
    published = _parse_time(post.get("created_time") if fb else post.get("timestamp"))
    item = _upsert_item(db, source, str(post["id"]), "post")
    item.title = _title(post.get("message") if fb else post.get("caption"), "(no text)" if fb else "(no caption)")
    item.url = post.get("permalink_url") if fb else post.get("permalink")
    item.published_at = published or item.published_at
    item.meta = {
        **(item.meta or {}),
        "thumbnail": post.get("full_picture") if fb else post.get("thumbnail_url") or post.get("media_url"),
        "media_type": post.get("status_type") if fb else post.get("media_product_type") or post.get("media_type"),
        "links": _post_links(post, fb),
        **extra,
    }
    db.flush()
    pub_day = published.astimezone(tz).date() if published else None
    days = _lifetime(item, totals, pub_day, today)
    for day, values in days.items():
        _put_day(db, source, item.id, day_bucket(day, tz), values)
    return set(days)


def sum_posts_into_page(db: Session, source: Source, days: set[date], metrics: tuple[str, ...], tz) -> None:
    for day in days:
        bucket = day_bucket(day, tz)
        rows = dict(
            db.execute(
                select(MetricPoint.metric, func.sum(MetricPoint.value))
                .where(
                    MetricPoint.source_id == source.id,
                    MetricPoint.item_id.is_not(None),
                    MetricPoint.granularity == "day",
                    MetricPoint.bucket == bucket,
                    MetricPoint.metric.in_(metrics),
                )
                .group_by(MetricPoint.metric)
            ).all()
        )
        _put_day(db, source, None, bucket, {m: rows.get(m, 0) for m in metrics})


def months_from_days(db: Session, source: Source, first: date, last: date, metrics: tuple[str, ...], tz) -> None:
    month = local_month_start(day_bucket(first, tz), tz)
    end = day_bucket(last, tz)
    while month <= end:
        _sum_from(db, source, "day", "month", month, next_local_month(month, tz), metrics)
        month = next_local_month(month, tz)


# ----------------------------------------------------------------------------- connecting


def connect(db: Session, source: Source, user_token: str, client=None) -> dict:
    """After the consent screen: pick the Page or Instagram account, or ask the admin to choose."""
    values = source_secrets(source)
    found = candidates(source.kind, accounts(user_token, source.config or {}, values.get("client_secret", ""), client))
    if not found:
        raise ConnectorError("meta_no_pages" if source.kind == "facebook" else "meta_no_instagram")
    wanted = (source.config or {}).get("account_id")
    pick = next((c for c in found if c["id"] == wanted), None) or (found[0] if len(found) == 1 else None)
    if pick is None:
        values["candidates"] = found
        source.secret_enc = encrypt_secret(json.dumps(values))
        source.config = {
            **(source.config or {}),
            "choices": [{k: c.get(k) for k in ("id", "name", "page")} for c in found],
        }
        db.commit()
        return {"choose": True}
    return choose(db, source, pick["id"], found)


def choose(db: Session, source: Source, account_id: str, found: list[dict] | None = None) -> dict:
    values = source_secrets(source)
    found = found if found is not None else values.get("candidates") or []
    pick = next((c for c in found if c["id"] == account_id), None)
    if pick is None:
        raise ConnectorError("meta_choice_invalid")
    values.pop("candidates", None)
    values["page_token"] = pick["token"]
    source.secret_enc = encrypt_secret(json.dumps(values))
    keep = {k: v for k, v in (source.config or {}).items() if k in SETTINGS}
    source.config = {
        **keep,
        "account_id": pick["id"],
        "account_name": pick["name"],
        "account_url": pick["url"],
        "page_name": pick.get("page"),
        "history_done": False,
    }
    source.last_error = None
    db.commit()
    return {"account_id": pick["id"], "name": pick["name"]}


SETTINGS = ("client_id", "config_id", "graph_version", "metric_overrides")


def disconnect(db: Session, source: Source) -> None:
    values = {k: v for k, v in source_secrets(source).items() if k == "client_secret"}
    source.secret_enc = encrypt_secret(json.dumps(values)) if values else None
    source.config = {k: v for k, v in (source.config or {}).items() if k in SETTINGS}
    db.commit()


# ----------------------------------------------------------------------------- sync


def is_due(source: Source, now: datetime) -> bool:
    cfg = source.config or {}
    if not cfg.get("account_id") or cfg.get("demo"):
        return False
    if not cfg.get("history_done"):
        return True
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
    api = Graph(source, client)
    source.last_poll_at = now
    try:
        run = _sync_facebook if source.kind == "facebook" else _sync_instagram
        try:
            result = run(db, source, cfg, api, now, tz)
        except InvalidMetric as exc:  # Meta renamed a metric: look the names up again next time
            cfg.pop("metric_names", None)
            raise ConnectorError("meta_metric_changed") from exc
    except ConnectorError as exc:
        db.rollback()
        source = db.get(Source, source.id)
        source.last_poll_at = now
        source.last_error = str(exc)
        source.last_error_at = now
        if str(exc) == "meta_metric_changed":
            source.config = {k: v for k, v in (source.config or {}).items() if k != "metric_names"}
        db.commit()
        raise
    source.config = cfg
    source.last_ok_at = now
    source.last_error = None
    db.commit()
    result["api_calls"] = api.calls
    return result


def _windows(first: date, last: date, span: int) -> Iterator[tuple[date, date]]:
    start = first
    while start <= last:
        end = min(last, start + timedelta(days=span - 1))
        yield start, end
        start = end + timedelta(days=1)


def _unix(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), UTC).timestamp())


def _post_insights(api: Graph, ids: list[str], names: dict[str, str]) -> dict[str, dict[str, Any]]:
    if not ids or not names:
        return {}
    metric = ",".join(dict.fromkeys(names.values()))
    by_name = {v: k for k, v in names.items()}
    out: dict[str, dict[str, Any]] = {}
    for pid, (status, body) in zip(ids, api.batch([f"{pid}/insights?metric={metric}" for pid in ids]), strict=True):
        if status != 200:
            try:
                _check(status or 500, body)
            except InvalidMetric:
                raise
            except ConnectorError as exc:
                if str(exc).startswith(("meta_reconnect", "meta_rate_limit")):
                    raise
            continue  # e.g. a post from before the account became professional: counts only
        vals: dict[str, Any] = {}
        for series in (body or {}).get("data") or []:
            key = by_name.get(series.get("name"))
            values = series.get("values") or []
            if key and values:
                vals[key] = values[-1].get("value")
            elif key and "total_value" in series:
                vals[key] = (series.get("total_value") or {}).get("value")
        out[pid] = vals
    return out


def _posts(api: Graph, cfg: dict, edge: str, fields: str, today: date, since_days: int) -> Iterator[list[dict]]:
    """The recent posts every run, plus a slice of the older ones until the history is in."""
    seen: set[str] = set()
    since = _unix(today - timedelta(days=since_days))
    params = {"fields": fields, "limit": PAGE_SIZE}
    if edge.endswith("/posts"):
        params["since"] = since
    for rows, _ in api.pages(edge, params, POST_PAGES_PER_RUN):
        recent = [r for r in rows if _post_time(r) is None or _post_time(r) >= since]
        seen.update(r["id"] for r in recent)
        if recent:
            yield recent
        if len(recent) < len(rows):
            break
    if cfg.get("posts_done"):
        return
    oldest = _unix(today - timedelta(days=FB_HISTORY_DAYS))
    params = {"fields": fields, "limit": PAGE_SIZE}
    if cfg.get("posts_after"):
        params["after"] = cfg["posts_after"]
    after = None
    for rows, after in api.pages(edge, params, POST_PAGES_PER_RUN):
        keep = [r for r in rows if r["id"] not in seen and (_post_time(r) or oldest) >= oldest]
        if keep:
            yield keep
        if len(keep) < len([r for r in rows if r["id"] not in seen]):
            after = None
            break
        if after:
            cfg["posts_after"] = after
    if after is None:
        cfg["posts_done"] = True
        cfg.pop("posts_after", None)


def _post_time(row: dict) -> int | None:
    dt = _parse_time(row.get("created_time") or row.get("timestamp"))
    return int(dt.timestamp()) if dt else None


def _sync_facebook(db: Session, source: Source, cfg: dict, api: Graph, now: datetime, tz) -> dict:
    page_id = cfg["account_id"]
    today = now.astimezone(tz).date()
    page = api.get(page_id, {"fields": "name,link,followers_count,fan_count"})
    cfg["account_name"] = page.get("name") or cfg.get("account_name")
    cfg["followers"] = int(page.get("followers_count") or page.get("fan_count") or 0)

    # Page totals per day: two years once, the last few days every run.
    names = metric_names(api, cfg, "page", page_id, today)
    first_day = today - timedelta(days=RECENT_DAYS)
    if not cfg.get("days_done"):
        first_day = today - timedelta(days=FB_HISTORY_DAYS - 1)
    changed: set[date] = set()
    if names:
        for start, end in _windows(first_day, today, INSIGHTS_SPAN):
            data = api.get(
                f"{page_id}/insights",
                {
                    "metric": ",".join(dict.fromkeys(names.values())),
                    "period": "day",
                    "since": _unix(start),
                    "until": _unix(end + timedelta(days=1)),
                },
            )
            changed |= store_page_series(db, source, data.get("data") or [], names, tz)
    cfg["days_done"] = True

    # Posts: lifetime totals, turned into what each post gained per day.
    fields = (
        "id,message,created_time,permalink_url,full_picture,status_type,shares,attachments{unshimmed_url,url},"
        "comments.summary(true).limit(0),reactions.summary(true).limit(0)"
    )
    post_names: dict[str, str] | None = None
    n = 0
    for rows in _posts(api, cfg, f"{page_id}/posts", fields, today, POST_REFRESH_DAYS):
        if post_names is None:
            post_names = metric_names(api, cfg, "post", rows[0]["id"], today)
        insights = _post_insights(api, [r["id"] for r in rows], post_names)
        for post in rows:
            ins = insights.get(post["id"], {})
            totals = {
                FB_REACTIONS: _number(((post.get("reactions") or {}).get("summary") or {}).get("total_count")),
                FB_COMMENTS: _number(((post.get("comments") or {}).get("summary") or {}).get("total_count")),
                FB_SHARES: _number((post.get("shares") or {}).get("count")),
                **{k: _number(v) for k, v in ins.items() if k in (FB_VIEWS, FB_REACH, FB_CLICKS)},
            }
            extra = {"reactions": ins["reactions_by_type"]} if isinstance(ins.get("reactions_by_type"), dict) else {}
            changed |= store_post(db, source, post, totals, extra, today, tz)
            n += 1
    db.flush()
    sum_posts_into_page(db, source, changed, FB_FROM_POSTS, tz)
    cfg["history_done"] = bool(cfg.get("posts_done"))
    if changed:
        months_from_days(db, source, min(changed), today, FB_DAY_METRICS, tz)
    rebuild_gauge(
        db, source, FB_FOLLOWERS, FB_FOLLOWS, FB_UNFOLLOWS, log_count(cfg, today, cfg["followers"]), today, tz
    )
    return {"posts": n, "days": len(changed)}


def _sync_instagram(db: Session, source: Source, cfg: dict, api: Graph, now: datetime, tz) -> dict:
    ig_id = cfg["account_id"]
    today = now.astimezone(tz).date()
    account = api.get(ig_id, {"fields": "username,name,followers_count,media_count"})
    if account.get("username"):
        cfg["account_name"] = f"@{account['username']}"
    cfg["followers"] = int(account.get("followers_count") or 0)
    cfg["media_count"] = int(account.get("media_count") or 0)

    # Account totals per day: Meta only gives a total per request, so one request per day.
    names = metric_names(api, cfg, "page", ig_id, today)
    days = [today - timedelta(days=i) for i in range(RECENT_DAYS + 1)]
    until = date.fromisoformat(cfg["days_until"]) if cfg.get("days_until") else today - timedelta(days=RECENT_DAYS)
    oldest = today - timedelta(days=IG_HISTORY_DAYS - 1)
    history = [until - timedelta(days=i + 1) for i in range(IG_DAYS_PER_RUN)]
    history = [d for d in history if d >= oldest]
    if history:
        cfg["days_until"] = min(history).isoformat()
    cfg["days_done"] = not history or min(history) <= oldest
    changed: set[date] = set()
    by_name = {v: k for k, v in names.items()}
    for day in [*days, *history]:
        if not names:
            break
        data = api.get(
            f"{ig_id}/insights",
            {
                "metric": ",".join(dict.fromkeys(names.values())),
                "period": "day",
                "metric_type": "total_value",
                "since": _unix(day),
                "until": _unix(day + timedelta(days=1)),
            },
        )
        values = {
            by_name[s["name"]]: _number((s.get("total_value") or {}).get("value"))
            for s in data.get("data") or []
            if s.get("name") in by_name
        }
        _put_day(db, source, None, day_bucket(day, tz), {k: values.get(k, 0) for k in names})
        changed.add(day)

    # New followers per day (Meta keeps 30 days and only for accounts with 100+ followers).
    try:
        data = api.get(
            f"{ig_id}/insights",
            {
                "metric": "follower_count",
                "period": "day",
                "since": _unix(today - timedelta(days=29)),
                "until": _unix(today),
            },
        )
        changed |= store_page_series(db, source, data.get("data") or [], {IG_FOLLOWS: "follower_count"}, tz)
    except (InvalidMetric, ConnectorError) as exc:
        if str(exc).startswith(("meta_reconnect", "meta_rate_limit")):
            raise
        log.info("Instagram follower_count unavailable for source %s: %s", source.id, exc)

    # Posts (feed and reels).
    fields = (
        "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count,thumbnail_url,media_url"
    )
    post_names: dict[str, str] | None = None
    n = 0
    for rows in _posts(api, cfg, f"{ig_id}/media", fields, today, POST_REFRESH_DAYS):
        if post_names is None:
            post_names = metric_names(api, cfg, "post", rows[0]["id"], today)
        insights = _post_insights(api, [r["id"] for r in rows], post_names)
        for post in rows:
            totals = {
                IG_LIKES: _number(post.get("like_count")),
                IG_COMMENTS: _number(post.get("comments_count")),
                **{k: _number(v) for k, v in insights.get(post["id"], {}).items()},
            }
            changed |= store_post(db, source, post, totals, {}, today, tz)
            n += 1
    db.flush()
    cfg["history_done"] = bool(cfg.get("posts_done") and cfg.get("days_done"))
    if changed:
        months_from_days(db, source, min(changed), today, IG_DAY_METRICS, tz)
    rebuild_gauge(db, source, IG_FOLLOWERS, IG_FOLLOWS, None, log_count(cfg, today, cfg["followers"]), today, tz)
    return {"posts": n, "days": len(changed)}
