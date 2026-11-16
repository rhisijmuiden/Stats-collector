"""Website numbers pushed by the Stats Collector WordPress plugin.

The plugin sends a signed JSON batch every minute (see `docs/manual/en/wordpress.md` and
`wordpress-plugin/stats-collector`). Every hour and day in a batch carries the full value of that
bucket so far, so a batch replaces what is stored; sending the same batch twice changes nothing.

Request headers:
  X-SC-Key        the site key shown under Sources (not secret, identifies the source)
  X-SC-Timestamp  Unix time in seconds; must be within five minutes of the server clock
  X-SC-Signature  "sha256=" + hex HMAC-SHA256(secret, timestamp + "." + raw body)

Body (version 1):
  site     {url, name, timezone, plugin, wp}
  authors  [{id, name, email}]
  items    [{id, type, title, url, published_at, authors: [id], categories: [..], tags: [..], comments,
             modified_at, words, images, featured_image, video, revisions, updates,
             seo: {plugin, keyword, score, readability} | null}]
  hours    [{hour (ISO, UTC), post (0 = whole site), views, visitors, read_seconds, reads, shares, comments}]
  days     [{day (YYYY-MM-DD, site time zone), post, visitors, referrers: {domain: n}, devices: {type: n},
             scroll: {"0"|"25"|"50"|"75"|"100": n}, campaigns: {"source|medium|campaign": n},
             searches: {term: n}, searches_empty: {term: n}}]   (searches only on the site row, post 0)
  live       {at, readers, posts: {post id: readers}}        readers in the last five minutes
  production {scheduled, drafts, pending, pending_comments, scheduled_items: [{id, title, at, author}]}
A batch with "ping": true only checks the connection. Everything after the first line of "items" and
"days", and "live" and "production", came with plugin 0.4; older plugins simply leave them out.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets as pysecrets
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import ContentItem, DimensionPoint, ItemPerson, MetricPoint, Person, Source, User, utcnow
from ..security import encrypt_secret
from .collect import source_secrets
from .metrics import (
    WEB_COMMENTS,
    WEB_READ_SECONDS,
    WEB_READS,
    WEB_SHARES,
    WEB_VIEWS,
    WEB_VISITORS,
)
from .rollup import org_timezone, rollup_web

MAX_BODY = 2 * 1024 * 1024
MAX_SKEW = 300
MAX_ROWS = {"authors": 500, "items": 2000, "hours": 20000, "days": 5000}
MAX_AGE_DAYS = 400
DIMENSIONS = {
    "referrers": "referrer",
    "devices": "device",
    "scroll": "scroll",
    "campaigns": "campaign",
    "searches": "search",
    "searches_empty": "search_empty",
}
SITE_ONLY = ("searches", "searches_empty")
DIM_KEY = re.compile(r"^[a-z0-9.\-]{1,255}$")
SCROLL_KEY = re.compile(r"^(0|25|50|75|100)$")
CAMPAIGN_KEY = re.compile(r"^[\w .+\-]{0,60}\|[\w .+\-]{0,60}\|[\w .+\-]{0,60}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f<>]")


def clean_dim_key(dimension: str, key: Any) -> str | None:
    """The key as it is stored for a dimension, or None when it is not valid."""
    key = str(key or "")
    if dimension == "search" or dimension == "search_empty":
        key = " ".join(CONTROL.sub(" ", key).lower().split())[:100]
        return key or None
    key = key.strip().lower()[:255]
    if dimension == "scroll":
        return key if SCROLL_KEY.match(key) else None
    if dimension == "campaign":
        return key if CAMPAIGN_KEY.match(key) and key.strip("|") else None
    return key if DIM_KEY.match(key) else None


HOUR_FIELDS = {
    "views": WEB_VIEWS,
    "visitors": WEB_VISITORS,
    "read_seconds": WEB_READ_SECONDS,
    "reads": WEB_READS,
    "shares": WEB_SHARES,
    "comments": WEB_COMMENTS,
}
ITEM_KINDS = {"post": "article", "page": "page"}


class IngestError(Exception):
    """Rejected batch; the message is a short code returned to the plugin."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


# ----------------------------------------------------------------------------- keys and signature


def new_credentials(source: Source) -> str:
    """Give a website source a fresh site key and secret. Returns the secret (shown once)."""
    secret = pysecrets.token_urlsafe(32)
    source.webhook_token = "sck_" + pysecrets.token_urlsafe(18)
    values = {**source_secrets(source), "ingest_secret": secret}
    source.secret_enc = encrypt_secret(json.dumps(values))
    return secret


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def authenticate(db: Session, key: str | None, timestamp: str | None, signature: str | None, body: bytes) -> Source:
    if not key or not timestamp or not signature:
        raise IngestError("missing_signature", 401)
    source = db.execute(
        select(Source).where(Source.kind == "wordpress", Source.webhook_token == key)
    ).scalar_one_or_none()
    secret = source_secrets(source).get("ingest_secret") if source else None
    # Compare against something even for an unknown key, so timing does not reveal valid keys.
    expected = sign(secret or "unknown", timestamp, body)
    if not hmac.compare_digest(expected, signature.strip()) or source is None or not secret:
        raise IngestError("bad_signature", 401)
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise IngestError("bad_timestamp", 401) from exc
    if abs(time.time() - ts) > MAX_SKEW:
        raise IngestError("clock_skew", 401)
    if not source.enabled:
        raise IngestError("source_disabled", 403)
    return source


# ----------------------------------------------------------------------------- parsing helpers


def _num(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 and v < 1e12 else 0.0


def _str(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _post_id(value: Any) -> int | None:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if 0 <= v < 2**53 else None


def _list(payload: dict, key: str) -> list:
    rows = payload.get(key) or []
    if not isinstance(rows, list):
        raise IngestError(f"bad_{key}")
    if len(rows) > MAX_ROWS[key]:
        raise IngestError(f"too_many_{key}", 413)
    return [r for r in rows if isinstance(r, dict)]


# ----------------------------------------------------------------------------- people and items


def _person_key(source: Source, wp_user_id: int) -> str:
    return f"wordpress:{source.id}:{wp_user_id}"


def upsert_people(db: Session, source: Source, authors: list[dict]) -> dict[int, Person]:
    people = list(db.execute(select(Person).where(Person.tenant_id == source.tenant_id)).scalars())
    by_key = {k: p for p in people for k in (p.external_ids or {})}
    by_email = {p.email.lower(): p for p in people if p.email}
    users = {u.email.lower(): u for u in db.execute(select(User).where(User.tenant_id == source.tenant_id)).scalars()}
    out: dict[int, Person] = {}
    for a in authors:
        wp_id = _post_id(a.get("id"))
        if not wp_id:
            continue
        key = _person_key(source, wp_id)
        name = _str(a.get("name"), 200) or f"#{wp_id}"
        email = _str(a.get("email"), 320).lower() or None
        person = by_key.get(key) or (by_email.get(email) if email else None)
        if person is None:
            person = Person(tenant_id=source.tenant_id, display_name=name, email=email, external_ids={})
            db.add(person)
            people.append(person)
        if key not in (person.external_ids or {}):
            person.external_ids = {**(person.external_ids or {}), key: wp_id}
        person.display_name = name
        if email:
            person.email = email
            by_email[email] = person
        if person.user_id is None and email and email in users:
            person.user_id = users[email].id
        by_key[key] = person
        out[wp_id] = person
    db.flush()
    return out


def _known_people(db: Session, source: Source) -> dict[int, Person]:
    prefix = f"wordpress:{source.id}:"
    out = {}
    for p in db.execute(select(Person).where(Person.tenant_id == source.tenant_id)).scalars():
        for key, wp_id in (p.external_ids or {}).items():
            if key.startswith(prefix):
                out[int(wp_id)] = p
    return out


def _article_details(row: dict) -> dict:
    """Length, media, updates and SEO of an article (plugin 0.4 and later); missing fields are left out."""
    out: dict[str, Any] = {}
    for field in ("words", "images", "revisions", "updates"):
        if field in row:
            out[field] = min(int(_num(row.get(field))), 1_000_000)
    for field in ("featured_image", "video"):
        if field in row:
            out[field] = bool(row.get(field))
    modified = _time(row.get("modified_at"))
    if modified is not None:
        out["modified_at"] = modified.astimezone(UTC).isoformat()
    seo = row.get("seo")
    if isinstance(seo, dict) and seo.get("plugin") in ("yoast", "rankmath"):

        def score(value: Any) -> int | None:
            return None if value is None or value == "" else max(0, min(100, int(_num(value))))

        out["seo"] = {
            "plugin": seo["plugin"],
            "keyword": _str(seo.get("keyword"), 100),
            "score": score(seo.get("score")),
            "readability": score(seo.get("readability")),
        }
    elif "seo" in row:
        out["seo"] = None
    return out


def _live(value: Any, now: datetime) -> dict | None:
    if not isinstance(value, dict):
        return None
    posts = value.get("posts") if isinstance(value.get("posts"), dict) else {}
    clean = {}
    for key, n in list(posts.items())[:50]:
        post_id = _post_id(key)
        if post_id and _num(n):
            clean[str(post_id)] = int(_num(n))
    return {"at": now.isoformat(), "readers": int(_num(value.get("readers"))), "posts": clean}


def _production(value: Any, people: dict[int, Person], now: datetime) -> dict | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {"at": now.isoformat()}
    for field in ("scheduled", "drafts", "pending", "pending_comments"):
        out[field] = int(_num(value.get(field)))
    items = []
    for row in (value.get("scheduled_items") or [])[:20]:
        if not isinstance(row, dict):
            continue
        at = _time(row.get("at"))
        author = people.get(_post_id(row.get("author")) or 0)
        items.append(
            {
                "title": _str(row.get("title"), 300),
                "at": at.astimezone(UTC).isoformat() if at else None,
                "person_id": author.id if author else None,
            }
        )
    out["scheduled_items"] = items
    return out


def upsert_items(db: Session, source: Source, rows: list[dict], people: dict[int, Person]) -> dict[int, ContentItem]:
    existing = {
        i.external_id: i for i in db.execute(select(ContentItem).where(ContentItem.source_id == source.id)).scalars()
    }
    out: dict[int, ContentItem] = {}
    for row in rows:
        post_id = _post_id(row.get("id"))
        if not post_id:
            continue
        item = existing.get(str(post_id))
        if item is None:
            item = ContentItem(
                tenant_id=source.tenant_id, source_id=source.id, external_id=str(post_id), kind="article"
            )
            db.add(item)
            existing[str(post_id)] = item
        item.kind = ITEM_KINDS.get(_str(row.get("type"), 20), "article")
        item.title = _str(row.get("title"), 500) or item.title or f"#{post_id}"
        url = _str(row.get("url"), 1000)
        if url.startswith(("http://", "https://")):
            item.url = url
        item.published_at = _time(row.get("published_at")) or item.published_at
        cats = [_str(c, 100) for c in (row.get("categories") or []) if isinstance(c, str)][:20]
        tags = [_str(t, 100) for t in (row.get("tags") or []) if isinstance(t, str)][:50]
        item.category = cats[0] if cats else None
        item.tags = tags
        item.meta = {
            **(item.meta or {}),
            "post_type": _str(row.get("type"), 20) or "post",
            "categories": cats,
            "comments": int(_num(row.get("comments"))),
            **_article_details(row),
        }
        db.flush()
        author_ids = [a for a in (_post_id(x) for x in (row.get("authors") or [])) if a]
        if "authors" in row:
            db.execute(delete(ItemPerson).where(ItemPerson.item_id == item.id))
            seen = set()
            for n, wp_user in enumerate(author_ids[:10]):
                person = people.get(wp_user)
                if person is None or person.id in seen:
                    continue
                seen.add(person.id)
                db.add(ItemPerson(item_id=item.id, person_id=person.id, role="author" if n == 0 else "coauthor"))
        out[post_id] = item
    db.flush()
    return out


def _item_for(db: Session, source: Source, post_id: int, items: dict[int, ContentItem]) -> ContentItem | None:
    if post_id == 0:
        return None
    item = items.get(post_id)
    if item is None:
        item = db.execute(
            select(ContentItem).where(ContentItem.source_id == source.id, ContentItem.external_id == str(post_id))
        ).scalar_one_or_none()
        if item is None:  # numbers for a post we have not seen yet: keep them, details follow later
            item = ContentItem(
                tenant_id=source.tenant_id,
                source_id=source.id,
                external_id=str(post_id),
                kind="article",
                title=f"#{post_id}",
            )
            db.add(item)
            db.flush()
        items[post_id] = item
    return item


# ----------------------------------------------------------------------------- numbers


def _put(db: Session, source: Source, item_id: int | None, gran: str, bucket: datetime, values: dict[str, float]):
    db.execute(
        delete(MetricPoint).where(
            MetricPoint.source_id == source.id,
            MetricPoint.item_id.is_(None) if item_id is None else MetricPoint.item_id == item_id,
            MetricPoint.granularity == gran,
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
                    granularity=gran,
                    bucket=bucket,
                    value=value,
                )
            )


def _put_dims(db: Session, source: Source, item_id: int | None, bucket: datetime, dimension: str, values: dict):
    db.execute(
        delete(DimensionPoint).where(
            DimensionPoint.source_id == source.id,
            DimensionPoint.item_id.is_(None) if item_id is None else DimensionPoint.item_id == item_id,
            DimensionPoint.dimension == dimension,
            DimensionPoint.bucket == bucket,
        )
    )
    clean: dict[str, float] = {}
    for raw, value in list(values.items())[:200]:
        key = clean_dim_key(dimension, raw)
        if key and _num(value):
            clean[key] = clean.get(key, 0) + _num(value)
    for key, value in clean.items():
        db.add(
            DimensionPoint(
                tenant_id=source.tenant_id,
                source_id=source.id,
                item_id=item_id,
                dimension=dimension,
                key=key,
                bucket=bucket,
                value=value,
            )
        )


def ingest(db: Session, source: Source, payload: Any, now: datetime | None = None) -> dict:
    if not isinstance(payload, dict):
        raise IngestError("bad_json")
    now = now or utcnow()
    site = payload.get("site") if isinstance(payload.get("site"), dict) else {}
    cfg = dict(source.config or {})
    for key, field, limit in (("site_name", "name", 200), ("plugin_version", "plugin", 32), ("wp_version", "wp", 32)):
        if site.get(field):
            cfg[key] = _str(site.get(field), limit)
    if site.get("timezone"):
        cfg["site_timezone"] = _str(site.get("timezone"), 64)
    source.config = cfg
    source.last_poll_at = now
    source.last_ok_at = now
    source.last_error = None
    if payload.get("ping"):
        db.commit()
        return {"ok": True, "source": source.name}

    authors = _list(payload, "authors")
    item_rows = _list(payload, "items")
    hours = _list(payload, "hours")
    days = _list(payload, "days")

    people = {**_known_people(db, source), **upsert_people(db, source, authors)}
    items = upsert_items(db, source, item_rows, people)
    extra = {
        key: parsed
        for key, parsed in (
            ("live", _live(payload.get("live"), now)),
            ("production", _production(payload.get("production"), people, now)),
        )
        if parsed is not None
    }
    if extra:
        source.config = {**(source.config or {}), **extra}
    tz = org_timezone(db)
    oldest = now - timedelta(days=MAX_AGE_DAYS)
    newest = now + timedelta(hours=1)
    first: datetime | None = None
    last: datetime | None = None
    stored = {"hours": 0, "days": 0, "skipped": 0}

    for row in hours:
        bucket = _time(row.get("hour"))
        post_id = _post_id(row.get("post", 0))
        if bucket is None or post_id is None or not (oldest <= bucket <= newest):
            stored["skipped"] += 1
            continue
        bucket = bucket.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        item = _item_for(db, source, post_id, items)
        values = {metric: round(_num(row.get(field)), 3) for field, metric in HOUR_FIELDS.items()}
        _put(db, source, item.id if item else None, "hour", bucket, values)
        stored["hours"] += 1
        first = min(first or bucket, bucket)
        last = max(last or bucket, bucket)

    for row in days:
        try:
            day = date.fromisoformat(str(row.get("day")))
        except ValueError:
            stored["skipped"] += 1
            continue
        bucket = datetime.combine(day, dtime(0), tz).astimezone(UTC)
        post_id = _post_id(row.get("post", 0))
        if post_id is None or not (oldest <= bucket <= newest):
            stored["skipped"] += 1
            continue
        item = _item_for(db, source, post_id, items)
        item_id = item.id if item else None
        _put(db, source, item_id, "day", bucket, {WEB_VISITORS: round(_num(row.get("visitors")), 3)})
        for field, dimension in DIMENSIONS.items():
            if isinstance(row.get(field), dict) and (item_id is None or field not in SITE_ONLY):
                _put_dims(db, source, item_id, bucket, dimension, row[field])
        stored["days"] += 1
        first = min(first or bucket, bucket)
        last = max(last or bucket, bucket)

    db.flush()
    if first is not None and last is not None:
        rollup_web(db, source, first, last, tz)
    db.commit()
    return {"ok": True, "items": len(items), "people": len(people), **stored}
