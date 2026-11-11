"""Alerts on outliers: a message in Microsoft Teams and/or by email when a story, post or channel
suddenly does much better than usual.

Two kinds of rule:
  item     a story, post or video published in the last three days has more views (interactions on
           Bluesky and Mastodon) than `factor` times the median of what that channel's items of the
           last 30 days reached
  channel  a channel's last full hour (website views, radio and stream listeners) is `factor` times
           the same hour in the previous four weeks; social media report per day, so for them
           yesterday is compared with the 28 days before

Every outlier is stored as an AlertEvent and reported once. Nothing is sent in a rule's quiet hours.
Teams: a Workflows (Power Automate) or incoming-webhook address; the message is an Adaptive Card.
"""

from __future__ import annotations

import html
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AlertEvent, AlertRule, ContentItem, MetricPoint, Source, utcnow
from ..security import decrypt_secret
from . import mail, settings_store
from .measures import INTERACTIONS, NO_VIEWS, STREAMS, VIEWS, aware, item_values, main_measure, typical
from .metrics import LIVE_AVG, WEB_VIEWS
from .rollup import hour_floor, local_day_start, org_timezone

log = logging.getLogger(__name__)

ITEM_AGE = timedelta(days=3)
HISTORY = timedelta(days=30)
WEEKS = 4
MIN_HOURS = 2  # earlier hours needed to know what is normal
MIN_DAYS = 7

TEXTS = {
    "en": {
        "item_title": "🔥 Going hard: {title}",
        "item_body": "{value} {measure} on {channel}, {factor}× what a {channel} item usually reaches ({usual}).",
        "channel_title": "📈 {channel} is busier than usual",
        "channel_body": "{value} {measure} {when}, {factor}× the usual {usual}.",
        "hour": "between {start} and {end}",
        "day": "yesterday",
        "open": "Open",
        "test_title": "Test alert from {app}",
        "test_body": 'This is how alerts of the rule "{rule}" will look.',
        "views": "views",
        "interactions": "interactions",
        "listeners": "listeners on average",
    },
    "nl": {
        "item_title": "🔥 Gaat hard: {title}",
        "item_body": "{value} {measure} op {channel}, {factor}× wat een item van {channel} meestal haalt ({usual}).",
        "channel_title": "📈 {channel} is drukker dan normaal",
        "channel_body": "{value} {measure} {when}, {factor}× het gebruikelijke {usual}.",
        "hour": "tussen {start} en {end}",
        "day": "gisteren",
        "open": "Openen",
        "test_title": "Testmelding van {app}",
        "test_body": 'Zo zien meldingen van de regel "{rule}" eruit.',
        "views": "weergaven",
        "interactions": "interacties",
        "listeners": "luisteraars gemiddeld",
    },
}


@dataclass
class Outlier:
    key: str
    source: Source
    measure: str
    value: float
    usual: float
    item: ContentItem | None = None
    start: datetime | None = None  # the hour or day of a channel outlier
    span: str = "hour"


def _fmt(n: float, lang: str) -> str:
    s = f"{n:,.0f}"
    return s.replace(",", ".") if lang == "nl" else s


def _sources(db: Session, rule: AlertRule) -> list[Source]:
    stmt = select(Source).where(Source.enabled.is_(True))
    if rule.source_ids:
        stmt = stmt.where(Source.id.in_([int(i) for i in rule.source_ids]))
    return list(db.execute(stmt).scalars())


# ----------------------------------------------------------------------------- finding outliers


def item_outliers(db: Session, rule: AlertRule, now: datetime) -> list[Outlier]:
    out: list[Outlier] = []
    for source in _sources(db, rule):
        if source.kind in STREAMS:
            continue
        measure = main_measure(source.kind)
        items = list(
            db.execute(
                select(ContentItem).where(
                    ContentItem.source_id == source.id,
                    ContentItem.published_at >= now - HISTORY,
                    ContentItem.published_at <= now,
                )
            ).scalars()
        )
        if not items:
            continue
        values = item_values(db, [i.id for i in items])
        recent = [i for i in items if aware(i.published_at) >= now - ITEM_AGE]
        earlier = [values[i.id][measure] for i in items if aware(i.published_at) < now - ITEM_AGE]
        usual = typical(earlier)
        if not usual:
            continue
        for item in recent:
            value = values[item.id][measure]
            if value >= rule.min_value and value >= rule.factor * usual:
                out.append(Outlier(f"item:{item.id}", source, measure, value, usual, item=item))
    return out


def _hour_values(db: Session, source: Source, metric: str, hours: list[datetime]) -> dict[datetime, float]:
    rows = db.execute(
        select(MetricPoint.bucket, func.sum(MetricPoint.value))
        .where(
            MetricPoint.source_id == source.id,
            MetricPoint.item_id.is_(None),
            MetricPoint.granularity == "hour",
            MetricPoint.metric == metric,
            MetricPoint.bucket.in_(hours),
        )
        .group_by(MetricPoint.bucket)
    ).all()
    return {aware(b): float(v or 0) for b, v in rows}


def channel_outliers(db: Session, rule: AlertRule, now: datetime) -> list[Outlier]:
    out: list[Outlier] = []
    hour = hour_floor(now) - timedelta(hours=1)
    tz = org_timezone(db)
    today = local_day_start(now, tz)
    for source in _sources(db, rule):
        if source.kind in STREAMS or source.kind == "wordpress":
            metric = LIVE_AVG if source.kind in STREAMS else WEB_VIEWS
            hours = [hour - timedelta(weeks=w) for w in range(WEEKS + 1)]
            values = _hour_values(db, source, metric, hours)
            value = values.get(hour)
            earlier = [values[h] for h in hours[1:] if h in values]
            usual = typical(earlier, MIN_HOURS)
            measure = "listeners" if source.kind in STREAMS else "views"
            key = f"source:{source.id}:{hour.isoformat()}"
            start, span = hour, "hour"
        else:
            metrics = INTERACTIONS if source.kind in NO_VIEWS else VIEWS
            rows = db.execute(
                select(MetricPoint.bucket, func.sum(MetricPoint.value))
                .where(
                    MetricPoint.source_id == source.id,
                    MetricPoint.item_id.is_(None),
                    MetricPoint.granularity == "day",
                    MetricPoint.metric.in_(metrics),
                    MetricPoint.bucket >= today - timedelta(days=30),
                    MetricPoint.bucket < today,
                )
                .group_by(MetricPoint.bucket)
            ).all()
            days = sorted((aware(b), float(v or 0)) for b, v in rows)
            if not days or days[-1][0] < today - timedelta(hours=26):
                continue  # no number for yesterday (yet)
            start, value = days[-1]
            usual = typical([v for _, v in days[:-1]][-28:], MIN_DAYS)
            measure = main_measure(source.kind)
            key = f"source:{source.id}:{start.astimezone(tz).date().isoformat()}"
            span = "day"
        if value is None or not usual:
            continue
        if value >= rule.min_value and value >= rule.factor * usual:
            out.append(Outlier(key, source, measure, value, usual, start=start, span=span))
    return out


def in_quiet_hours(rule: AlertRule, local: datetime) -> bool:
    if not (rule.quiet_start and rule.quiet_end):
        return False
    try:
        start = time.fromisoformat(rule.quiet_start)
        end = time.fromisoformat(rule.quiet_end)
    except ValueError:
        return False
    t = local.time()
    return start <= t < end if start <= end else (t >= start or t < end)


# ----------------------------------------------------------------------------- messages


def app_link(path: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}{path}"


def message(db: Session, rule: AlertRule, o: Outlier) -> tuple[str, str, str | None]:
    """(title, text, link) in the rule's language."""
    lang = rule.language if rule.language in TEXTS else "en"
    t = TEXTS[lang]
    tz = org_timezone(db)
    values = {
        "channel": o.source.name,
        "value": _fmt(o.value, lang),
        "usual": _fmt(o.usual, lang),
        "factor": f"{o.value / o.usual:.1f}".replace(".", "," if lang == "nl" else "."),
        "measure": t[o.measure],
    }
    if o.item is not None:
        title = t["item_title"].format(title=(o.item.title or "").strip()[:200] or o.source.name)
        text = t["item_body"].format(**values)
        url = o.item.url or app_link(f"/content?item={o.item.id}")
    else:
        if o.span == "hour" and o.start is not None:
            local = o.start.astimezone(tz)
            when = t["hour"].format(start=local.strftime("%H:%M"), end=(local + timedelta(hours=1)).strftime("%H:%M"))
        else:
            when = t["day"]
        title = t["channel_title"].format(**values)
        text = t["channel_body"].format(when=when, **values)
        url = app_link("/")
    return title, text, url


def teams_payload(title: str, text: str, url: str | None, open_label: str, accent: str = "accent") -> dict:
    """An Adaptive Card that Teams Workflows and incoming webhooks both accept."""
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True, "color": accent},
            {"type": "TextBlock", "text": text, "wrap": True},
        ],
    }
    if url:
        card["actions"] = [{"type": "Action.OpenUrl", "title": open_label, "url": url}]
    return {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}
        ],
    }


def send_teams(webhook: str, payload: dict) -> None:
    resp = httpx.post(webhook, json=payload, timeout=15)
    if resp.status_code >= 300:
        raise RuntimeError(f"teams: HTTP {resp.status_code}")


def deliver(db: Session, rule: AlertRule, title: str, text: str, url: str | None) -> tuple[list[str], str]:
    """Send to Teams and email. Returns (channels that worked, error text)."""
    lang = rule.language if rule.language in TEXTS else "en"
    done: list[str] = []
    errors: list[str] = []
    webhook = decrypt_secret(rule.teams_webhook_enc) if rule.teams_webhook_enc else None
    if webhook:
        try:
            send_teams(webhook, teams_payload(title, text, url, TEXTS[lang]["open"]))
            done.append("teams")
        except Exception as exc:  # noqa: BLE001 - network or Teams error: record and go on
            errors.append(str(exc)[:200])
    if rule.emails:
        cfg = settings_store.get_section(db, "email")
        if mail.configured(cfg):
            esc = html.escape
            link = (
                f'<p><a href="{esc(url)}" style="background:#0e9f8e;color:#fff;padding:8px 14px;border-radius:8px;'
                f'text-decoration:none;font-weight:600">{esc(TEXTS[lang]["open"])}</a></p>'
                if url
                else ""
            )
            try:
                mail.send(
                    cfg,
                    mail.OutgoingMail(
                        to=list(rule.emails),
                        subject=title,
                        text=f"{text}\n\n{url or ''}",
                        html=f'<div style="font-family:Inter,Arial,sans-serif;color:#1d2433;max-width:600px">'
                        f'<h2 style="font-size:18px">{esc(title)}</h2><p>{esc(text)}</p>{link}</div>',
                    ),
                )
                done.append("email")
            except mail.MailError as exc:
                errors.append(f"email: {exc}"[:200])
        else:
            errors.append("email: not configured")
    return done, "; ".join(errors)[:500]


def check(db: Session, now: datetime | None = None) -> int:
    """Find new outliers for every enabled rule and report them. Returns how many were found."""
    now = now or utcnow()
    local = now.astimezone(org_timezone(db))
    found = 0
    for rule in db.execute(select(AlertRule).where(AlertRule.enabled.is_(True))).scalars().all():
        if in_quiet_hours(rule, local):
            continue
        try:
            outliers = item_outliers(db, rule, now) if rule.scope == "item" else channel_outliers(db, rule, now)
        except Exception:  # noqa: BLE001 - one rule must not stop the others
            log.exception("alert rule %s failed", rule.id)
            continue
        known = set(db.execute(select(AlertEvent.key).where(AlertEvent.rule_id == rule.id)).scalars())
        for o in outliers:
            if o.key in known:
                continue
            title, text, url = message(db, rule, o)
            event = AlertEvent(
                rule_id=rule.id,
                key=o.key,
                source_id=o.source.id,
                item_id=o.item.id if o.item else None,
                title=title[:500],
                measure=o.measure,
                value=o.value,
                usual=o.usual,
                at=now,
            )
            db.add(event)
            try:
                db.commit()
            except IntegrityError:  # found by a parallel run
                db.rollback()
                continue
            event.delivered, event.error = deliver(db, rule, title, text, url)
            db.commit()
            found += 1
    return found


def test(db: Session, rule: AlertRule) -> tuple[list[str], str]:
    from ..api.settings import effective_theme

    lang = rule.language if rule.language in TEXTS else "en"
    app = effective_theme(db).get("app_name") or "Stats Collector"
    t = TEXTS[lang]
    return deliver(
        db, rule, t["test_title"].format(app=app), t["test_body"].format(rule=rule.name), app_link("/alerts")
    )


def recent(db: Session, limit: int = 50) -> list[dict]:
    sources = {s.id: s for s in db.execute(select(Source)).scalars()}
    rules = {r.id: r.name for r in db.execute(select(AlertRule)).scalars()}
    rows = db.execute(select(AlertEvent).order_by(AlertEvent.at.desc(), AlertEvent.id.desc()).limit(limit)).scalars()
    out = []
    for e in rows:
        s = sources.get(e.source_id) if e.source_id else None
        out.append(
            {
                "id": e.id,
                "rule": rules.get(e.rule_id),
                "title": e.title,
                "source": {"id": s.id, "name": s.name, "kind": s.kind} if s else None,
                "item_id": e.item_id,
                "measure": e.measure,
                "value": round(e.value),
                "usual": round(e.usual),
                "factor": round(e.value / e.usual, 1) if e.usual else None,
                "at": aware(e.at).isoformat(),
                "delivered": e.delivered or [],
                "error": e.error,
            }
        )
    return out


def counts_by_rule(db: Session, since: datetime) -> dict[int, int]:
    out: dict[int, int] = defaultdict(int)
    for rule_id, n in db.execute(
        select(AlertEvent.rule_id, func.count()).where(AlertEvent.at >= since).group_by(AlertEvent.rule_id)
    ).all():
        out[rule_id] = n
    return out
