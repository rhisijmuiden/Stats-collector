"""Links between social posts or videos and the website articles they point to.

A Facebook post, Instagram post or YouTube video is linked to an article automatically when one of
the links in its text (or the link attached to a Facebook post) leads to that article's address.
Addresses are compared after normalising: no scheme, no "www.", no trailing slash, no fragment and
no tracking parameters. Editors can add links by hand, and remove automatic ones; a removed
automatic link is remembered so the next run does not bring it back.

The article's editors are credited with the numbers of the posts that link to their articles.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import ContentItem, ItemLink

log = logging.getLogger(__name__)

SOCIAL_KINDS = ("post", "video")
ARTICLE_KINDS = ("article", "page")
URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)
TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|igshid|igsh|mc_cid|mc_eid|si|ref|ref_src|_ga)$", re.IGNORECASE)
# Redirect wrappers whose real destination is in a query parameter.
SHIMS = {"l.facebook.com": "u", "lm.facebook.com": "u", "l.instagram.com": "u", "www.youtube.com/redirect": "q"}
MAX_LINKS = 20


def extract_urls(*texts: str | None) -> list[str]:
    """Web addresses found in free text, in order and without duplicates."""
    out: list[str] = []
    for text in texts:
        for match in URL_RE.findall(text or ""):
            url = match.rstrip(".,;:!?…")
            if url not in out:
                out.append(url)
    return out[:MAX_LINKS]


def _unshim(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.lower()
    for prefix, param in SHIMS.items():
        shim_host, _, shim_path = prefix.partition("/")
        if host == shim_host and (not shim_path or parts.path.strip("/") == shim_path):
            target = dict(parse_qsl(parts.query)).get(param)
            if target:
                return unquote(target)
    return url


def normalize_url(url: str | None) -> str | None:
    """A comparable form of an address: host and path in lower case, without tracking parameters."""
    if not url:
        return None
    url = _unshim(url.strip())
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = parts.netloc.lower().split("@")[-1]
    if host.endswith(":443") or host.endswith(":80"):
        host = host.rsplit(":", 1)[0]
    host = host.removeprefix("www.").removeprefix("m.")
    if not host or "." not in host:
        return None
    path = unquote(parts.path).rstrip("/").lower()
    query = sorted((k, v) for k, v in parse_qsl(parts.query) if not TRACKING.match(k))
    return host + path + (f"?{urlencode(query)}" if query else "")


def article_index(db: Session) -> dict[str, int]:
    """Normalised address → article id, for every article or page (its address and its ?p= short link)."""
    index: dict[str, int] = {}
    for item in db.execute(select(ContentItem).where(ContentItem.kind.in_(ARTICLE_KINDS))).scalars():
        key = normalize_url(item.url)
        if not key:
            continue
        index.setdefault(key, item.id)
        if item.external_id.isdigit():
            index.setdefault(f"{key.split('/', 1)[0]}?p={item.external_id}", item.id)
    return index


def auto_link(db: Session) -> dict:
    """Bring the automatic links in line with the links found in posts and videos."""
    index = article_index(db)
    existing = {
        (f, t): m for f, t, m in db.execute(select(ItemLink.from_item_id, ItemLink.to_item_id, ItemLink.method)).all()
    }
    added = removed = 0
    for item in db.execute(select(ContentItem).where(ContentItem.kind.in_(SOCIAL_KINDS))).scalars():
        meta = item.meta or {}
        refused = {int(i) for i in meta.get("unlinked") or []}
        wanted = {index[k] for k in (normalize_url(u) for u in meta.get("links") or []) if k in index} - refused
        wanted.discard(item.id)
        current = {t for (f, t), m in existing.items() if f == item.id and m == "url"}
        for to_id in wanted - current:
            if (item.id, to_id) not in existing:
                db.add(ItemLink(from_item_id=item.id, to_item_id=to_id, method="url"))
                added += 1
        stale = current - wanted
        if stale:
            db.execute(
                delete(ItemLink).where(
                    ItemLink.from_item_id == item.id, ItemLink.to_item_id.in_(stale), ItemLink.method == "url"
                )
            )
            removed += len(stale)
    db.commit()
    if added or removed:
        log.info("item links: %d added, %d removed", added, removed)
    return {"added": added, "removed": removed}


def add(db: Session, social: ContentItem, article: ContentItem) -> None:
    """A link made by hand (also undoes an earlier removal)."""
    meta = dict(social.meta or {})
    if article.id in (meta.get("unlinked") or []):
        meta["unlinked"] = [i for i in meta["unlinked"] if i != article.id]
        social.meta = meta
    link = db.get(ItemLink, (social.id, article.id))
    if link is None:
        db.add(ItemLink(from_item_id=social.id, to_item_id=article.id, method="manual"))
    db.commit()


def remove(db: Session, social: ContentItem, article: ContentItem) -> bool:
    link = db.get(ItemLink, (social.id, article.id))
    if link is None:
        return False
    if link.method != "manual":  # remember, so the next automatic run leaves it out
        meta = dict(social.meta or {})
        meta["unlinked"] = sorted({*(meta.get("unlinked") or []), article.id})
        social.meta = meta
    db.delete(link)
    db.commit()
    return True
