"""Weekly summary per editor: an email every week with the editor's numbers of the past week.

Who gets one: every editor (a person credited on articles, see Content and editors) with an email
address — their own, or that of the app user they are linked to — who had numbers or published
something last week, unless they are switched off under Weekly summary.

What it holds: views, interactions and social views of their items over the last full week
(Monday to Sunday, organisation time zone), the change against the week before, how many items
they published, their best five items, and optionally their place among all editors.

The worker looks every ten minutes; the summary goes out once a week on the chosen day and time.
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ContentItem, ItemPerson, Person, Source, User, utcnow
from . import mail, settings_store
from .measures import aware, item_values
from .rollup import local_day_start, org_timezone

log = logging.getLogger(__name__)
KEY = "digest"
TOP = 5

TEXTS = {
    "en": {
        "subject": "Your week in numbers: {period}",
        "hello": "Hi {name},",
        "intro": "This is how your stories did last week ({period}).",
        "views": "Views",
        "interactions": "Interactions",
        "social": "Social views",
        "published": "Published",
        "vs": "vs. the week before",
        "best": "Your best items",
        "rank": "You were number {rank} of {total} editors by views.",
        "none": "No numbers for your items last week.",
        "open": "Open your numbers",
        "footer": "You get this email every week from {app}. Ask an administrator to switch it off.",
    },
    "nl": {
        "subject": "Jouw week in cijfers: {period}",
        "hello": "Hoi {name},",
        "intro": "Zo deden jouw verhalen het vorige week ({period}).",
        "views": "Weergaven",
        "interactions": "Interacties",
        "social": "Sociale weergaven",
        "published": "Gepubliceerd",
        "vs": "t.o.v. de week ervoor",
        "best": "Jouw best scorende stukken",
        "rank": "Je stond op plek {rank} van {total} redacteuren op weergaven.",
        "none": "Geen cijfers voor jouw stukken vorige week.",
        "open": "Open jouw cijfers",
        "footer": "Je krijgt deze e-mail elke week van {app}. Vraag een beheerder om hem uit te zetten.",
    },
}


def settings(db: Session) -> dict:
    return settings_store.get_section(db, KEY)


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def last_week(db: Session, now: datetime) -> tuple[date, datetime, datetime, datetime]:
    """(monday, start, end, start of the week before) of the last full week."""
    tz = org_timezone(db)
    today = now.astimezone(tz).date()
    monday = today - timedelta(days=today.weekday() + 7)

    def at(d: date) -> datetime:
        return local_day_start(datetime.combine(d, datetime.min.time(), tz), tz)

    return monday, at(monday), at(monday + timedelta(days=7)), at(monday - timedelta(days=7))


def recipient(db: Session, person: Person) -> tuple[str | None, str]:
    """(email, language) of an editor."""
    default = settings_store.get_section(db, "general").get("default_language", "en")
    user = db.get(User, person.user_id) if person.user_id else None
    if user is not None and user.is_active:
        return (person.email or user.email), user.language or default
    return person.email, default


def _change(now: float, before: float) -> float | None:
    return round((now - before) / before * 100, 1) if before else None


def editor_week(db: Session, person: Person, now: datetime | None = None) -> dict:
    """The numbers for one editor; `ranking` holds everyone's views to place them."""
    from ..api.content import _editor_rows

    now = now or utcnow()
    monday, start, end, before = last_week(db, now)
    rows = {r["id"]: r for r in _editor_rows(db, start, end, "day")}
    prev = {r["id"]: r for r in _editor_rows(db, before, start, "day", [person.id])}
    mine = rows.get(person.id) or {}
    old = prev.get(person.id) or {}
    item_ids = list(db.execute(select(ItemPerson.item_id).where(ItemPerson.person_id == person.id)).scalars())
    values = item_values(db, item_ids, start, end)
    best_ids = sorted(
        (i for i in item_ids if values[i]["views"] or values[i]["interactions"]),
        key=lambda i: -(values[i]["views"] or values[i]["interactions"]),
    )[:TOP]
    items = {i.id: i for i in db.execute(select(ContentItem).where(ContentItem.id.in_(best_ids))).scalars()}
    sources = {s.id: s for s in db.execute(select(Source)).scalars()}
    published = sum(
        1
        for i in db.execute(select(ContentItem).where(ContentItem.id.in_(item_ids))).scalars()
        if i.published_at and start <= aware(i.published_at) < end
    )
    views = (mine.get("metrics") or {}).get("views", 0)
    inter = sum((mine.get("metrics") or {}).get(k, 0) for k in ("likes", "comments", "shares"))
    social = (mine.get("social") or {}).get("views", 0)
    old_views = (old.get("metrics") or {}).get("views", 0)
    old_inter = sum((old.get("metrics") or {}).get(k, 0) for k in ("likes", "comments", "shares"))
    old_social = (old.get("social") or {}).get("views", 0)
    ranked = sorted(rows.values(), key=lambda r: -r["metrics"]["views"])
    rank = next((n + 1 for n, r in enumerate(ranked) if r["id"] == person.id), None)
    return {
        "person": {"id": person.id, "name": person.display_name},
        "week": week_key(monday),
        "start": monday.isoformat(),
        "end": (monday + timedelta(days=6)).isoformat(),
        "views": round(views),
        "interactions": round(inter),
        "social_views": round(social),
        "published": published,
        "change": {
            "views": _change(views, old_views),
            "interactions": _change(inter, old_inter),
            "social_views": _change(social, old_social),
        },
        "best": [
            {
                "id": i,
                "title": items[i].title,
                "url": items[i].url,
                "source": sources[items[i].source_id].name if items[i].source_id in sources else "",
                "views": round(values[i]["views"]),
                "interactions": round(values[i]["interactions"]),
            }
            for i in best_ids
            if i in items
        ],
        "rank": rank if views else None,
        "editors": len(ranked),
    }


def _num(v: float, lang: str) -> str:
    s = f"{v:,.0f}"
    return s.replace(",", ".") if lang == "nl" else s


def _period(data: dict, lang: str) -> str:
    a, b = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
    if lang == "nl":
        return f"{a.day}-{a.month} t/m {b.day}-{b.month}-{b.year}"
    return f"{a.isoformat()} – {b.isoformat()}"


def build_mail(db: Session, data: dict, to: str, lang: str, ranking: bool = True) -> mail.OutgoingMail:
    from ..api.settings import effective_theme
    from .alerts import app_link

    theme = effective_theme(db)
    app = theme.get("app_name") or "Stats Collector"
    accent = ((theme.get("colors") or {}).get("light") or {}).get("accent", "#0E9F8E")
    t = TEXTS.get(lang, TEXTS["en"])
    esc = html.escape
    period = _period(data, lang)
    kpis = [
        (t["views"], data["views"], data["change"]["views"]),
        (t["interactions"], data["interactions"], data["change"]["interactions"]),
        (t["social"], data["social_views"], data["change"]["social_views"]),
        (t["published"], data["published"], None),
    ]
    cells = "".join(
        f'<td style="padding:12px 14px;border:1px solid #e2e7ef;border-radius:10px;vertical-align:top">'
        f'<div style="font-size:12px;color:#5d6b80">{esc(label)}</div>'
        f'<div style="font-size:22px;font-weight:700">{_num(value, lang)}</div>'
        + (
            f'<div style="font-size:12px;color:{"#1e9e5a" if change >= 0 else "#d93036"}">'
            f"{'▲' if change >= 0 else '▼'} {abs(change):.0f}% {esc(t['vs'])}</div>"
            if change is not None
            else ""
        )
        + "</td>"
        for label, value, change in kpis
    )
    best = "".join(
        '<tr><td style="padding:6px 0;border-bottom:1px solid #eef1f5">'
        + (f'<a href="{esc(b["url"])}" style="color:#152033">{esc(b["title"])}</a>' if b["url"] else esc(b["title"]))
        + f'<div style="font-size:12px;color:#5d6b80">{esc(b["source"])}</div></td>'
        f'<td style="padding:6px 0 6px 12px;border-bottom:1px solid #eef1f5;text-align:right;white-space:nowrap">'
        f"{_num(b['views'] or b['interactions'], lang)}</td></tr>"
        for b in data["best"]
    )
    has_numbers = data["views"] or data["interactions"] or data["social_views"] or data["published"]
    rank = t["rank"].format(rank=data["rank"], total=data["editors"]) if ranking and data.get("rank") else ""
    link = app_link("/editors")
    body = (
        '<div style="font-family:Inter,Arial,sans-serif;color:#152033;max-width:640px">'
        f'<p style="font-size:12px;color:#5d6b80">{esc(app)}</p>'
        f'<h1 style="font-size:20px;margin:0 0 12px">{esc(t["hello"].format(name=data["person"]["name"]))}</h1>'
        f"<p>{esc(t['intro'].format(period=period))}</p>"
        + (
            f'<table style="border-collapse:separate;border-spacing:8px;margin:0 -8px"><tr>{cells}</tr></table>'
            if has_numbers
            else f"<p>{esc(t['none'])}</p>"
        )
        + (
            f'<h2 style="font-size:16px;margin:20px 0 6px">{esc(t["best"])}</h2>'
            f'<table style="width:100%;border-collapse:collapse;font-size:14px">{best}</table>'
            if best
            else ""
        )
        + (f"<p>{esc(rank)}</p>" if rank else "")
        + f'<p style="margin:20px 0"><a href="{esc(link)}" '
        f'style="background:{esc(accent)};color:#fff;padding:10px 16px;'
        f'border-radius:8px;text-decoration:none;font-weight:600">{esc(t["open"])}</a></p>'
        f'<p style="font-size:12px;color:#5d6b80">{esc(t["footer"].format(app=app))}</p></div>'
    )
    lines = [t["hello"].format(name=data["person"]["name"]), "", t["intro"].format(period=period)]
    lines += [f"{label}: {_num(value, lang)}" for label, value, _ in kpis]
    if data["best"]:
        lines += ["", t["best"]] + [
            f"- {b['title']} ({_num(b['views'] or b['interactions'], lang)})" for b in data["best"]
        ]
    if rank:
        lines += ["", rank]
    lines += ["", f"{t['open']}: {link}"]
    return mail.OutgoingMail(to=[to], subject=t["subject"].format(period=period), text="\n".join(lines), html=body)


def editors(db: Session) -> list[dict]:
    """Every editor with the address their summary goes to."""
    cfg = settings(db)
    excluded = {int(i) for i in cfg.get("excluded_person_ids") or []}
    out = []
    for p in db.execute(select(Person).order_by(Person.display_name)).scalars():
        email, lang = recipient(db, p)
        out.append(
            {"id": p.id, "name": p.display_name, "email": email, "language": lang, "enabled": p.id not in excluded}
        )
    return out


def due(db: Session, now: datetime) -> bool:
    cfg = settings(db)
    if not cfg.get("enabled"):
        return False
    local = now.astimezone(org_timezone(db))
    if local.weekday() != int(cfg.get("weekday", 0)) or local.strftime("%H:%M") < (cfg.get("time") or "08:00"):
        return False
    return cfg.get("last_week") != week_key(last_week(db, now)[0])


def run_due(db: Session, now: datetime | None = None) -> int:
    """Send the weekly summaries when it is time. Returns how many emails went out."""
    now = now or utcnow()
    if not due(db, now):
        return 0
    cfg = settings(db)
    settings_store.update_section(db, KEY, {"last_week": week_key(last_week(db, now)[0])})
    email_cfg = settings_store.get_section(db, "email")
    if not mail.configured(email_cfg):
        log.warning("weekly summary: email is not set up")
        return 0
    sent = 0
    for e in editors(db):
        if not e["enabled"] or not e["email"]:
            continue
        person = db.get(Person, e["id"])
        data = editor_week(db, person, now)
        if not (data["views"] or data["interactions"] or data["social_views"] or data["published"]):
            continue
        try:
            mail.send(email_cfg, build_mail(db, data, e["email"], e["language"], bool(cfg.get("ranking", True))))
            sent += 1
        except mail.MailError as exc:
            log.warning("weekly summary to %s failed: %s", e["email"], exc)
    log.info("weekly summary: %d sent", sent)
    return sent
