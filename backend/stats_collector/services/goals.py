"""Goals: progress per day, the target in force on each day, a trend forecast and notifications.

Two kinds of goal:
  level  followers: the count on a day (sum over the chosen sources) must reach the target
  total  views, reach, interactions, watch minutes: the sum since the start date must reach it

Targets can be changed at any time; every change is a GoalRevision, so a chart shows the target
that applied on each day, not only the current one.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Goal, GoalRevision, MetricPoint, Source, User, utcnow
from . import mail, settings_store
from .followers import day_bucket
from .rollup import org_timezone

log = logging.getLogger(__name__)

GOAL_METRICS: dict[str, tuple[str, ...]] = {
    "followers": ("yt_subscribers", "fb_followers", "ig_followers", "bsky_followers", "masto_followers"),
    "views": ("web_views", "yt_views", "fb_views", "ig_views"),
    "reach": ("web_visitors", "fb_reach", "ig_reach"),
    "interactions": (
        "web_shares",
        "web_comments",
        "yt_likes",
        "yt_comments",
        "yt_shares",
        "fb_reactions",
        "fb_comments",
        "fb_shares",
        "ig_likes",
        "ig_comments",
        "ig_shares",
        "ig_saves",
        "bsky_likes",
        "bsky_reposts",
        "bsky_replies",
        "bsky_quotes",
        "masto_favourites",
        "masto_boosts",
        "masto_replies",
    ),
    "watch_minutes": ("live_minutes", "yt_watch_minutes"),
}
LEVEL = ("followers",)
TREND_DAYS = 14
BEHIND_EVERY = timedelta(days=7)


def kind(goal: Goal) -> str:
    return "level" if goal.metric in LEVEL else "total"


def _sources(db: Session, goal: Goal) -> list[int]:
    stmt = select(Source.id)
    if goal.source_ids:
        stmt = stmt.where(Source.id.in_([int(i) for i in goal.source_ids]))
    return list(db.execute(stmt).scalars())


def daily(db: Session, goal: Goal, first: date, last: date, tz) -> dict[date, float]:
    """The goal's value per day: the count on that day (level) or that day's sum (total)."""
    ids = _sources(db, goal)
    if not ids:
        return {}
    rows = db.execute(
        select(MetricPoint.source_id, MetricPoint.bucket, func.sum(MetricPoint.value))
        .where(
            MetricPoint.source_id.in_(ids),
            MetricPoint.item_id.is_(None),
            MetricPoint.granularity == "day",
            MetricPoint.metric.in_(GOAL_METRICS[goal.metric]),
            MetricPoint.bucket >= day_bucket(first, tz) - timedelta(days=400 if kind(goal) == "level" else 0),
            MetricPoint.bucket < day_bucket(last + timedelta(days=1), tz),
        )
        .group_by(MetricPoint.source_id, MetricPoint.bucket)
    ).all()
    per_source: dict[int, dict[date, float]] = defaultdict(dict)
    for source_id, bucket, value in rows:
        b = bucket if bucket.tzinfo else bucket.replace(tzinfo=UTC)
        per_source[source_id][b.astimezone(tz).date()] = float(value or 0)
    out: dict[date, float] = {}
    day = first
    if kind(goal) == "total":
        while day <= last:
            out[day] = sum(s.get(day, 0) for s in per_source.values())
            day += timedelta(days=1)
        return out
    # Level: carry each source's last known count forward over days without a number.
    last_seen: dict[int, float] = {}
    for sid, values in per_source.items():
        before = [d for d in values if d < first]
        if before:
            last_seen[sid] = values[max(before)]
    while day <= last:
        for sid, values in per_source.items():
            if day in values:
                last_seen[sid] = values[day]
        if last_seen:
            out[day] = sum(last_seen.values())
        day += timedelta(days=1)
    return out


def revisions(db: Session, goal: Goal) -> list[GoalRevision]:
    return list(
        db.execute(
            select(GoalRevision)
            .where(GoalRevision.goal_id == goal.id)
            .order_by(GoalRevision.changed_at, GoalRevision.id)
        ).scalars()
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def progress(db: Session, goal: Goal, now: datetime | None = None) -> dict:
    """Everything a goal card and chart need."""
    now = now or utcnow()
    tz = org_timezone(db)
    today = now.astimezone(tz).date()
    end = goal.end_date
    last = min(today, end) if end else today
    first = goal.start_date
    values = daily(db, goal, first, max(first, last), tz) if first <= today else {}
    days = sorted(values)
    if kind(goal) == "total":
        running, series = 0.0, []
        for d in days:
            running += values[d]
            series.append(round(running, 2))
        baseline = 0.0
    else:
        series = [round(values[d], 2) for d in days]
        baseline = series[0] if series else 0.0
    current = series[-1] if series else 0.0

    # The target in force on each day (revisions are dated when they were made).
    revs = revisions(db, goal)
    targets = []
    for d in days:
        target = goal.target
        for r in revs:
            if _aware(r.changed_at).astimezone(tz).date() <= d:
                target = r.target
        if revs and _aware(revs[0].changed_at).astimezone(tz).date() > d:
            target = revs[0].target
        targets.append(target)

    # Trend: the average change per day over the last two weeks, carried on to the end date.
    forecast = None
    rate = 0.0
    if len(series) >= 2:
        span = min(TREND_DAYS, len(series) - 1)
        rate = (series[-1] - series[-1 - span]) / span
    if end and end > last and series:
        forecast = round(current + rate * (end - last).days, 2)
    elif series:
        forecast = current
    span_target = goal.target - baseline
    done = current - baseline
    pct = 100.0 if span_target <= 0 else max(0.0, min(100.0, done / span_target * 100))
    reached = current >= goal.target
    if reached:
        status = "reached"
    elif end and today > end:
        status = "missed"
    elif forecast is not None and end and forecast < goal.target:
        status = "behind"
    else:
        status = "on_track"
    needed = None
    if end and not reached and end > last:
        needed = round((goal.target - current) / max((end - last).days, 1), 2)
    return {
        "kind": kind(goal),
        "current": round(current, 2),
        "baseline": round(baseline, 2),
        "progress": round(pct, 1),
        "rate_per_day": round(rate, 2),
        "needed_per_day": needed,
        "forecast": forecast,
        "status": status,
        "days": [d.isoformat() for d in days],
        "values": series,
        "targets": targets,
    }


# ----------------------------------------------------------------------------- notifications

TEXTS = {
    "en": {
        "reached": ("Goal reached: {name}", 'The goal "{name}" has been reached: {current} of {target}.'),
        "behind": (
            "Goal falling behind: {name}",
            'The goal "{name}" is behind: {current} of {target}. At the current pace it ends at about '
            "{forecast} on {end}; {needed} per day is needed.",
        ),
    },
    "nl": {
        "reached": ("Doel gehaald: {name}", 'Het doel "{name}" is gehaald: {current} van {target}.'),
        "behind": (
            "Doel loopt achter: {name}",
            'Het doel "{name}" loopt achter: {current} van {target}. In het huidige tempo eindigt het rond '
            "{forecast} op {end}; er is {needed} per dag nodig.",
        ),
    },
}


def _recipients(db: Session, goal: Goal) -> list[tuple[str, str]]:
    """(email, language) pairs: the addresses on the goal, else whoever made it."""
    if goal.notify_emails:
        lang = settings_store.get_section(db, "general").get("default_language", "en")
        return [(e, lang) for e in goal.notify_emails]
    user = db.get(User, goal.created_by) if goal.created_by else None
    return [(user.email, user.language)] if user else []


def _fmt(n: float | None) -> str:
    return "–" if n is None else f"{n:,.0f}"


def check(db: Session, now: datetime | None = None) -> int:
    """Send the "reached" and "behind" emails that are due. Returns how many were sent."""
    now = now or utcnow()
    cfg = settings_store.get_section(db, "email")
    sent = 0
    for goal in db.execute(select(Goal).where(Goal.archived.is_(False))).scalars():
        p = progress(db, goal, now)
        event = None
        if p["status"] == "reached" and goal.reached_at is None:
            goal.reached_at = now
            event = "reached"
        elif p["status"] == "behind" and (
            goal.behind_notified_at is None or now - _aware(goal.behind_notified_at) >= BEHIND_EVERY
        ):
            goal.behind_notified_at = now
            event = "behind"
        db.commit()
        if not event or not goal.notify or not cfg.get("host"):
            continue
        for email, lang in _recipients(db, goal):
            subject, body = TEXTS.get(lang, TEXTS["en"])[event]
            values = {
                "name": goal.name,
                "current": _fmt(p["current"]),
                "target": _fmt(goal.target),
                "forecast": _fmt(p["forecast"]),
                "needed": _fmt(p["needed_per_day"]),
                "end": goal.end_date.isoformat() if goal.end_date else "–",
            }
            text = body.format(**values)
            try:
                mail.send(
                    cfg,
                    mail.OutgoingMail(
                        to=[email],
                        subject=subject.format(**values),
                        text=text,
                        html=f'<p style="font-family:Inter,Arial,sans-serif">{_escape(text)}</p>',
                    ),
                )
                sent += 1
            except mail.MailError as exc:
                log.warning("goal mail to %s failed: %s", email, exc)
    return sent


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
