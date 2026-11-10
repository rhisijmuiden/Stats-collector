"""Bluesky and Mastodon: public accounts read through their open APIs, no app review needed.

Bluesky   the public AppView (https://public.api.bsky.app), no login: the profile (follower count)
          and the author feed (posts with their like, repost, reply and quote counts).
Mastodon  the account's own server: /api/v1/accounts/lookup and /api/v1/accounts/:id/statuses
          (favourites, boosts, replies). An access token (scope read) is optional; some servers
          only answer with one.

Neither platform reports views or reach. What is stored, per day:
  post     what the post gained since the day before (from its totals; first sight: its whole
           total on the day it came out)
  account  the sum over its posts, plus new followers (net change of the follower count) and the
           follower count itself (gauge, worked back from the counts seen at every sync)

Every sync (hourly) re-reads the posts of the last 30 days. Right after adding an account the
older posts are read too, a few pages per run, back to one year.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from ..connectors import ConnectorError
from ..models import Source, utcnow
from .collect import source_secrets
from .followers import day_bucket, log_count, rebuild_gauge
from .links import extract_urls
from .meta import _lifetime, _put_day, _title, _upsert_item, months_from_days, sum_posts_into_page
from .metrics import (
    BSKY_DAY_METRICS,
    BSKY_FOLLOWERS,
    BSKY_FOLLOWS,
    BSKY_LIKES,
    BSKY_POST_METRICS,
    BSKY_QUOTES,
    BSKY_REPLIES,
    BSKY_REPOSTS,
    MASTO_BOOSTS,
    MASTO_DAY_METRICS,
    MASTO_FAVOURITES,
    MASTO_FOLLOWERS,
    MASTO_FOLLOWS,
    MASTO_POST_METRICS,
    MASTO_REPLIES,
)
from .rollup import org_timezone

log = logging.getLogger(__name__)

KINDS = ("bluesky", "mastodon")
BSKY_API = "https://public.api.bsky.app/xrpc"
SYNC_EVERY = timedelta(hours=1)
REFRESH_DAYS = 30
HISTORY_DAYS = 365
PAGES_PER_RUN = 10
GAUGE = {"bluesky": BSKY_FOLLOWERS, "mastodon": MASTO_FOLLOWERS}
FOLLOWS = {"bluesky": BSKY_FOLLOWS, "mastodon": MASTO_FOLLOWS}
POST_METRICS = {"bluesky": BSKY_POST_METRICS, "mastodon": MASTO_POST_METRICS}
DAY_METRICS = {"bluesky": BSKY_DAY_METRICS, "mastodon": MASTO_DAY_METRICS}
HANDLE = re.compile(r"^@?([a-z0-9][a-z0-9.-]{0,251}[a-z0-9])$", re.I)
ACCT = re.compile(r"^@?([a-z0-9_]{1,64})(@[a-z0-9.-]+)?$", re.I)


# ----------------------------------------------------------------------------- input


def clean_handle(value: str) -> str:
    """A Bluesky handle from what an admin typed: '@name.bsky.social', a profile link or a DID."""
    v = value.strip()
    m = re.match(r"^https?://bsky\.app/profile/([^/?#]+)", v)
    if m:
        v = m.group(1)
    if v.startswith("did:"):
        return v if re.fullmatch(r"did:[a-z]+:[A-Za-z0-9._:%-]{1,200}", v) else ""
    m = HANDLE.match(v)
    return m.group(1).lower() if m and "." in m.group(1) else ""


def clean_account(value: str, server: str) -> tuple[str, str]:
    """(server URL, username) from '@name@server', 'https://server/@name' or a name and a server."""
    v = value.strip()
    m = re.match(r"^(https?://[^/]+)/@([^/?#@]+)", v)
    if m:
        return m.group(1).lower(), m.group(2)
    m = ACCT.match(v)
    if not m:
        return server, ""
    if m.group(2):
        server = "https://" + m.group(2)[1:].lower()
    return server.rstrip("/"), m.group(1)


# ----------------------------------------------------------------------------- HTTP


def _client(client: httpx.Client | None = None) -> httpx.Client:
    return client or httpx.Client(
        timeout=httpx.Timeout(30.0, connect=10.0), headers={"User-Agent": "StatsCollector/1"}, follow_redirects=True
    )


def _get(client: httpx.Client, url: str, params: dict | None = None, token: str | None = None, kind: str = "") -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"unreachable: {exc.__class__.__name__}") from exc
    if resp.status_code == 429:
        raise ConnectorError("social_rate_limit")
    if resp.status_code in (401, 403):
        raise ConnectorError("masto_token_needed" if kind == "mastodon" else "social_forbidden")
    if resp.status_code in (400, 404):
        raise ConnectorError("social_account_not_found")
    if resp.status_code >= 400:
        raise ConnectorError(f"http_{resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ConnectorError("invalid_response") from exc


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _n(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------------- Bluesky


def _bsky_profile(client: httpx.Client, actor: str) -> dict:
    return _get(client, f"{BSKY_API}/app.bsky.actor.getProfile", {"actor": actor})


def _bsky_feed(client: httpx.Client, did: str, cursor: str | None) -> tuple[list[dict], str | None]:
    params = {"actor": did, "limit": 100, "filter": "posts_and_author_threads"}
    if cursor:
        params["cursor"] = cursor
    data = _get(client, f"{BSKY_API}/app.bsky.feed.getAuthorFeed", params)
    posts = []
    for row in data.get("feed") or []:
        post = row.get("post") or {}
        if row.get("reason") or (post.get("author") or {}).get("did") != did:
            continue  # a repost of someone else's post
        posts.append(post)
    return posts, data.get("cursor")


def _bsky_links(post: dict) -> list[str]:
    record = post.get("record") or {}
    found: list[str] = []
    for facet in record.get("facets") or []:
        for f in facet.get("features") or []:
            if isinstance(f.get("uri"), str) and f["uri"].startswith(("http://", "https://")):
                found.append(f["uri"])
    for embed in (post.get("embed") or {}, record.get("embed") or {}):
        ext = embed.get("external") or (embed.get("media") or {}).get("external") or {}
        if isinstance(ext.get("uri"), str) and ext["uri"].startswith(("http://", "https://")):
            found.append(ext["uri"])
    found += extract_urls(record.get("text"))
    return list(dict.fromkeys(found))[:20]


def _bsky_post(post: dict, handle: str) -> dict:
    record = post.get("record") or {}
    rkey = str(post.get("uri", "")).rsplit("/", 1)[-1]
    thumb = None
    embed = post.get("embed") or {}
    images = embed.get("images") or (embed.get("media") or {}).get("images") or []
    if images:
        thumb = images[0].get("thumb")
    elif (embed.get("external") or {}).get("thumb"):
        thumb = embed["external"]["thumb"]
    return {
        "id": str(post.get("uri")),
        "text": record.get("text"),
        "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
        "published": _time(record.get("createdAt") or post.get("indexedAt")),
        "thumbnail": thumb,
        "links": _bsky_links(post),
        "totals": {
            BSKY_LIKES: _n(post.get("likeCount")),
            BSKY_REPOSTS: _n(post.get("repostCount")),
            BSKY_REPLIES: _n(post.get("replyCount")),
            BSKY_QUOTES: _n(post.get("quoteCount")),
        },
    }


# ----------------------------------------------------------------------------- Mastodon


def _masto_account(client: httpx.Client, server: str, username: str, token: str | None) -> dict:
    return _get(client, f"{server}/api/v1/accounts/lookup", {"acct": username}, token, "mastodon")


def _masto_page(
    client: httpx.Client, server: str, account_id: str, max_id: str | None, token: str | None
) -> tuple[list[dict], str | None]:
    params: dict[str, Any] = {"limit": 40, "exclude_reblogs": "true"}
    if max_id:
        params["max_id"] = max_id
    rows = _get(client, f"{server}/api/v1/accounts/{quote(account_id)}/statuses", params, token, "mastodon")
    rows = rows if isinstance(rows, list) else []
    return rows, (str(rows[-1]["id"]) if len(rows) == 40 else None)


def _masto_text(html: Any) -> str:
    text = re.sub(r"<br\s*/?>|</p>\s*<p>", " ", str(html or ""))
    return unescape(re.sub(r"<[^>]+>", "", text))


def _masto_post(row: dict) -> dict:
    card = row.get("card") or {}
    links = [card["url"]] if isinstance(card.get("url"), str) else []
    links += [h for h in re.findall(r'href="(https?://[^"]+)"', str(row.get("content") or "")) if "/tags/" not in h]
    media = row.get("media_attachments") or []
    mentions = {m.get("url") for m in row.get("mentions") or []}
    return {
        "id": str(row.get("id")),
        "text": _masto_text(row.get("content")) or row.get("spoiler_text"),
        "url": row.get("url") or row.get("uri"),
        "published": _time(row.get("created_at")),
        "thumbnail": (media[0].get("preview_url") if media else None) or card.get("image"),
        "links": [u for u in dict.fromkeys(unescape(x) for x in links) if u not in mentions][:20],
        "totals": {
            MASTO_FAVOURITES: _n(row.get("favourites_count")),
            MASTO_BOOSTS: _n(row.get("reblogs_count")),
            MASTO_REPLIES: _n(row.get("replies_count")),
        },
        "reply": bool(row.get("in_reply_to_account_id"))
        and str(row.get("in_reply_to_account_id")) != str((row.get("account") or {}).get("id")),
    }


# ----------------------------------------------------------------------------- account and posts


def lookup(kind: str, cfg: dict, secrets: dict, client: httpx.Client | None = None) -> dict:
    """The account: {id, name, handle, url, followers, posts}. Used by "Test connection" and sync."""
    http = _client(client)
    if kind == "bluesky":
        handle = cfg.get("account") or ""
        if not handle:
            raise ConnectorError("social_account_not_found")
        p = _bsky_profile(http, handle)
        return {
            "id": p.get("did"),
            "name": p.get("displayName") or p.get("handle"),
            "handle": f"@{p.get('handle')}",
            "url": f"https://bsky.app/profile/{p.get('handle')}",
            "followers": int(p.get("followersCount") or 0),
            "posts": int(p.get("postsCount") or 0),
        }
    server, username = cfg.get("url") or "", cfg.get("account") or ""
    if not server or not username:
        raise ConnectorError("social_account_not_found")
    a = _masto_account(http, server, username, secrets.get("access_token"))
    acct = str(a.get("acct") or a.get("username") or username)
    return {
        "id": str(a.get("id")),
        "name": a.get("display_name") or a.get("username"),
        "handle": f"@{acct}" if "@" in acct else f"@{acct}@{server.split('://', 1)[-1]}",
        "url": a.get("url"),
        "followers": int(a.get("followers_count") or 0),
        "posts": int(a.get("statuses_count") or 0),
    }


def _pages(kind: str, http: httpx.Client, cfg: dict, secrets: dict, cursor: str | None) -> Iterator[tuple[list, Any]]:
    """Pages of posts (already in our shape), newest first, starting at `cursor`."""
    while True:
        if kind == "bluesky":
            rows, nxt = _bsky_feed(http, cfg["account_id"], cursor)
            posts = [_bsky_post(r, cfg.get("handle", "").lstrip("@") or cfg["account_id"]) for r in rows]
        else:
            rows, nxt = _masto_page(http, cfg["url"], cfg["account_id"], cursor, secrets.get("access_token"))
            posts = [p for p in (_masto_post(r) for r in rows) if not p["reply"]]
        yield posts, nxt
        if not nxt:
            return
        cursor = nxt


def _posts(kind: str, http: httpx.Client, cfg: dict, secrets: dict, today: date) -> Iterator[dict]:
    """The posts of the last 30 days every run, plus a slice of older ones until a year is in."""
    recent = datetime.combine(today - timedelta(days=REFRESH_DAYS), datetime.min.time(), UTC)
    oldest = datetime.combine(today - timedelta(days=HISTORY_DAYS), datetime.min.time(), UTC)
    seen: set[str] = set()
    for n, (posts, _nxt) in enumerate(_pages(kind, http, cfg, secrets, None)):
        new = [p for p in posts if (p["published"] or recent) >= recent]
        for p in new:
            seen.add(p["id"])
            yield p
        if len(new) < len(posts) or n + 1 >= PAGES_PER_RUN:
            break
    if cfg.get("posts_done"):
        return
    cursor, done = cfg.get("posts_cursor"), True
    for n, (posts, nxt) in enumerate(_pages(kind, http, cfg, secrets, cursor)):
        for p in posts:
            if p["id"] not in seen and (p["published"] or oldest) >= oldest:
                yield p
        if any((p["published"] or oldest) < oldest for p in posts) or not nxt:
            break
        cfg["posts_cursor"] = nxt
        if n + 1 >= PAGES_PER_RUN:
            done = False
            break
    if done:
        cfg["posts_done"] = True
        cfg.pop("posts_cursor", None)


def _store(db: Session, source: Source, post: dict, today: date, tz) -> set[date]:
    item = _upsert_item(db, source, post["id"], "post")
    item.title = _title(post["text"], "(no text)")
    item.url = post["url"]
    item.published_at = post["published"] or item.published_at
    item.meta = {**(item.meta or {}), "thumbnail": post["thumbnail"], "links": post["links"]}
    db.flush()
    pub = post["published"].astimezone(tz).date() if post["published"] else None
    days = _lifetime(item, post["totals"], pub, today)
    for day, values in days.items():
        _put_day(db, source, item.id, day_bucket(day, tz), values)
    return set(days)


# ----------------------------------------------------------------------------- sync


def is_due(source: Source, now: datetime) -> bool:
    cfg = source.config or {}
    if cfg.get("demo") or not cfg.get("account"):
        return False
    if not cfg.get("posts_done"):
        return True
    last = source.last_poll_at
    if last is None:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    return now - last >= SYNC_EVERY


def sync(db: Session, source: Source, now: datetime | None = None, client: httpx.Client | None = None) -> dict:
    if (source.config or {}).get("demo"):
        return {"demo": True}
    now = now or utcnow()
    tz = org_timezone(db)
    today = now.astimezone(tz).date()
    cfg = dict(source.config or {})
    secrets = source_secrets(source)
    http = _client(client)
    source.last_poll_at = now
    try:
        account = lookup(source.kind, cfg, secrets, http)
        if cfg.get("account_id") not in (None, account["id"]):
            cfg = {k: cfg[k] for k in ("url", "account") if k in cfg}  # another account: start again
        cfg.update(
            account_id=account["id"],
            account_name=account["name"],
            handle=account["handle"],
            account_url=account["url"],
            followers=account["followers"],
            post_count=account["posts"],
        )
        changed: set[date] = set()
        n = 0
        for post in _posts(source.kind, http, cfg, secrets, today):
            changed |= _store(db, source, post, today, tz)
            n += 1
        db.flush()
        if changed:
            sum_posts_into_page(db, source, changed, POST_METRICS[source.kind], tz)
        counts = log_count(cfg, today, account["followers"])
        _follows(db, source, counts, today, tz)
        rebuild_gauge(db, source, GAUGE[source.kind], FOLLOWS[source.kind], None, counts, today, tz)
        months_from_days(db, source, min([*changed, today]), today, DAY_METRICS[source.kind], tz)
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
    return {"posts": n, "days": len(changed)}


def _follows(db: Session, source: Source, counts: dict[date, int], today: date, tz) -> None:
    """New followers per day (net): the change from the last count seen on an earlier day."""
    earlier = [d for d in counts if d < today]
    if not earlier:
        return
    delta = counts[today] - counts[max(earlier)]
    _put_day(db, source, None, day_bucket(today, tz), {FOLLOWS[source.kind]: delta})
