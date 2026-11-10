"""Polls sources and stores what they report as content items and stream samples."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors import STREAM_KINDS, ConnectorError, PollResult, get_connector
from ..models import ContentItem, Source, StreamSample, utcnow
from ..security import decrypt_secret

log = logging.getLogger(__name__)


def source_secrets(source: Source) -> dict:
    raw = decrypt_secret(source.secret_enc) if source.secret_enc else None
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _parse_time(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def test_source(kind: str, config: dict, secrets: dict) -> PollResult:
    """Used by the "Test connection" button; stores nothing."""
    return get_connector(kind).poll(config, secrets)


def poll_source(db: Session, source: Source, now: datetime | None = None) -> PollResult | None:
    now = (now or utcnow()).replace(microsecond=0)
    source.last_poll_at = now
    try:
        result = get_connector(source.kind).poll(source.config or {}, source_secrets(source))
    except ConnectorError as exc:
        source.last_error = str(exc)
        source.last_error_at = now
        db.commit()
        return None
    except Exception as exc:  # pragma: no cover - unexpected bug; keep polling the others
        log.exception("poll of source %s failed", source.id)
        source.last_error = f"internal_error: {exc.__class__.__name__}"
        source.last_error_at = now
        db.commit()
        return None

    items = {
        i.external_id: i for i in db.execute(select(ContentItem).where(ContentItem.source_id == source.id)).scalars()
    }
    seen_ids = set()
    for obs in result.observations:
        item = items.get(obs.external_id)
        if item is None:
            item = ContentItem(
                tenant_id=source.tenant_id,
                source_id=source.id,
                kind=obs.kind,
                external_id=obs.external_id,
                title=obs.title,
                url=obs.url,
                published_at=_parse_time(obs.started_at) or (now if obs.kind == "broadcast" else None),
            )
            db.add(item)
            db.flush()
            items[obs.external_id] = item
        else:
            if obs.title and item.title != obs.title:
                item.title = obs.title
            if obs.online and item.ended_at is not None and item.kind == "broadcast":
                item.ended_at = None
        seen_ids.add(obs.external_id)
        db.add(
            StreamSample(
                tenant_id=source.tenant_id,
                source_id=source.id,
                item_id=item.id,
                ts=now,
                online=obs.online,
                value=obs.value if obs.online else 0,
                extra=obs.extra,
            )
        )
    if not result.observations:
        # Offline source: one zero sample so charts show the gap as zero, not as missing data.
        db.add(
            StreamSample(
                tenant_id=source.tenant_id, source_id=source.id, item_id=None, ts=now, online=False, value=0, extra={}
            )
        )
    # Broadcasts that are no longer reported have ended.
    for item in items.values():
        if item.kind == "broadcast" and item.ended_at is None and item.external_id not in seen_ids:
            item.ended_at = now
    source.last_ok_at = now
    source.last_error = None
    db.commit()
    return result


def due_sources(db: Session, now: datetime | None = None) -> list[Source]:
    now = now or utcnow()
    rows = db.execute(select(Source).where(Source.enabled.is_(True), Source.kind.in_(STREAM_KINDS))).scalars()
    due = []
    for s in rows:
        if (s.config or {}).get("demo"):
            continue
        last = _aware(s.last_poll_at)
        # A little slack so a 30 s interval polled by a 10 s beat does not drift to 40 s.
        if last is None or now - last >= timedelta(seconds=max(10, s.poll_seconds) - 5):
            due.append(s)
    return due
