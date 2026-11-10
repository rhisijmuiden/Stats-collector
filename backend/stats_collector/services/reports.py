"""Reports: blocks filled in for a period, frozen into a run with a link, a PDF and an email.

A run keeps the numbers as they were when it was made, so an archived report never changes. The
interactive page (/r/<token>) and the PDF show the same data; the PDF is that page printed by
headless Chromium.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import secrets
import shutil
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ContentItem, Goal, Report, ReportRun, User, utcnow
from ..security import encrypt_secret
from . import mail, settings_store
from .rollup import org_timezone

log = logging.getLogger(__name__)

PERIODS = ("yesterday", "last_week", "last_month", "last_7d", "last_30d", "last_90d")
SCHEDULES = ("none", "daily", "weekly", "monthly")
SEES_EDITORS = ("admin", "editor_in_chief")
PDF_TIMEOUT = 120


class ReportError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ----------------------------------------------------------------------------- periods


def _midnight(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time(), tz).astimezone(UTC)


def _window(first: date, last_excl: date, tz: ZoneInfo) -> tuple[datetime, datetime, str, list[datetime]]:
    days = (last_excl - first).days
    buckets = [_midnight(first + timedelta(days=i), tz) for i in range(days)]
    return _midnight(first, tz), _midnight(last_excl, tz), "day", buckets


def _month_start(d: date, back: int = 0) -> date:
    y, m = d.year, d.month - back
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def windows(kind: str, now: datetime, tz: ZoneInfo) -> tuple[tuple, tuple]:
    """The period a report covers, and the period before it for comparison (local whole days)."""
    today = _aware(now).astimezone(tz).date()
    if kind == "last_month":
        first, end = _month_start(today, 1), _month_start(today)
        return _window(first, end, tz), _window(_month_start(today, 2), first, tz)
    if kind == "last_week":
        end = today - timedelta(days=today.weekday())  # this Monday
        first = end - timedelta(days=7)
        return _window(first, end, tz), _window(first - timedelta(days=7), first, tz)
    days = {"yesterday": 1, "last_7d": 7, "last_30d": 30, "last_90d": 90}.get(kind)
    if days is None:
        raise ReportError("unknown_period")
    first = today - timedelta(days=days)
    return _window(first, today, tz), _window(first - timedelta(days=days), first, tz)


def next_run(report: Report, after: datetime, tz: ZoneInfo) -> datetime | None:
    """The first scheduled moment after a time, or None without a schedule."""
    if report.schedule not in ("daily", "weekly", "monthly") or not report.enabled:
        return None
    hh, mm = (int(x) for x in (report.send_time or "08:00").split(":"))
    local = _aware(after).astimezone(tz)
    day = local.date()
    for _ in range(400):
        ok = (
            report.schedule == "daily"
            or (report.schedule == "weekly" and day.weekday() == report.weekday)
            or (report.schedule == "monthly" and day.day == report.monthday)
        )
        if ok:
            at = datetime.combine(day, time(hh, mm), tz).astimezone(UTC)
            if at > _aware(after):
                return at
        day += timedelta(days=1)
    return None


# ----------------------------------------------------------------------------- data


def block_data(db: Session, block: dict, window: tuple, previous: tuple) -> dict:
    from ..api.content import _editor_rows, ranked_items
    from ..api.dashboards import measure_data
    from ..api.goals import _out as goal_out

    start, end, gran, _ = window
    kind = block.get("type")
    if kind in ("kpi", "chart"):
        split = "none" if kind == "kpi" else block.get("split", "platform")
        return measure_data(
            db, block["measure"], split, block.get("sources") or [], block.get("platforms") or [], window, previous
        )
    if kind == "top":
        stmt = select(ContentItem)
        if block.get("kind"):
            stmt = stmt.where(ContentItem.kind == block["kind"])
        sort, limit = block.get("sort", "views"), block.get("limit", 10)
        return {"items": ranked_items(db, stmt, start, end, gran, sort, limit, False)}
    if kind == "editors":
        return {"editors": _editor_rows(db, start, end, gran)[: block.get("limit", 10)]}
    if kind == "goals":
        goals = db.execute(select(Goal).where(Goal.archived.is_(False)).order_by(Goal.end_date, Goal.name)).scalars()
        return {"goals": [goal_out(db, g) for g in goals]}
    return {}


def has_editors(report: Report) -> bool:
    return any(b.get("type") == "editors" for b in report.blocks or [])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate(db: Session, report: Report, user_id: int | None, trigger: str = "manual", now: datetime | None = None):
    """Freeze the report for its period. Returns (run, token)."""
    now = now or utcnow()
    tz = org_timezone(db)
    window, previous = windows(report.period, now, tz)
    blocks = []
    for b in report.blocks or []:
        try:
            blocks.append({"block": b, "data": block_data(db, b, window, previous)})
        except Exception as exc:  # noqa: BLE001 - one block must not stop the report
            log.exception("report %s: block %s failed", report.id, b.get("id"))
            blocks.append({"block": b, "data": {}, "error": type(exc).__name__})
    token = secrets.token_urlsafe(32)
    title = report.title or report.name
    run = ReportRun(
        report_id=report.id,
        title=title,
        period_start=window[0],
        period_end=window[1],
        data={
            "title": title,
            "intro": report.intro or "",
            "language": report.language,
            "period": report.period,
            "timezone": str(tz),
            "start": window[0].isoformat(),
            "end": window[1].isoformat(),
            "generated_at": now.isoformat(),
            "blocks": blocks,
        },
        token_hash=_hash(token),
        token_enc=encrypt_secret(token),
        expires_at=now + timedelta(days=max(1, report.link_days or 30)),
        trigger=trigger,
        created_by=user_id,
    )
    db.add(run)
    db.commit()
    return run, token


def find_run(db: Session, token: str) -> ReportRun | None:
    return db.execute(select(ReportRun).where(ReportRun.token_hash == _hash(token))).scalar_one_or_none()


def link(token: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}/r/{token}"


# ----------------------------------------------------------------------------- PDF


def chromium_path() -> str | None:
    """Chromium for the PDF: SC_CHROMIUM_PATH, or chromium on the PATH (Debian package). None lets
    Playwright use its own browser, if one was installed with `playwright install chromium`."""
    configured = os.environ.get("SC_CHROMIUM_PATH")
    if configured:
        return configured if Path(configured).exists() else None
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def internal_base() -> str:
    cfg = get_settings()
    host = cfg.host if cfg.host not in ("0.0.0.0", "::", "") else "127.0.0.1"
    return os.environ.get("SC_INTERNAL_URL") or f"http://{host}:{cfg.port}"


def pdf_file(run: ReportRun) -> Path:
    return get_settings().data_dir / "reports" / f"{run.id}.pdf"


def render_pdf(run: ReportRun, token: str) -> bytes:
    """Print the report page to PDF with headless Chromium (driven by Playwright); the result is
    kept next to the run, so it is made once."""
    path = pdf_file(run)
    if path.exists():
        return path.read_bytes()
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ReportError("chromium_missing") from exc
    url = f"{internal_base()}/r/{token}?print=1"
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    executable_path=chromium_path(),
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
                )
            except PlaywrightError as exc:
                log.warning("chromium did not start: %s", exc)
                raise ReportError("chromium_missing") from exc
            try:
                page = browser.new_page(viewport={"width": 718, "height": 1000})
                page.goto(url, wait_until="networkidle", timeout=PDF_TIMEOUT * 1000)
                page.wait_for_selector(".report, .report-missing", timeout=30_000)
                if page.query_selector(".report-missing"):
                    raise ReportError("pdf_failed")
                page.wait_for_timeout(400)  # the charts draw without animation; give them a moment
                data = page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
            finally:
                browser.close()
    except PlaywrightError as exc:
        log.warning("report %s: PDF failed: %s", run.id, exc)
        raise ReportError("pdf_failed") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


# ----------------------------------------------------------------------------- email

TEXTS = {
    "en": {
        "subject": "{title} ({period})",
        "intro": "Your report for {period} is ready.",
        "open": "Open the interactive report",
        "until": "The link works until {date}.",
        "pdf": "The report is attached as a PDF.",
        "nopdf": "The PDF could not be made this time; the link has the full report.",
        "vs": "vs. previous period",
    },
    "nl": {
        "subject": "{title} ({period})",
        "intro": "Je rapport over {period} staat klaar.",
        "open": "Open het interactieve rapport",
        "until": "De link werkt tot {date}.",
        "pdf": "Het rapport zit als pdf in de bijlage.",
        "nopdf": "De pdf kon deze keer niet worden gemaakt; de link bevat het volledige rapport.",
        "vs": "t.o.v. vorige periode",
    },
}
MEASURES = {
    "en": {
        "reach": "Reach",
        "views": "Views",
        "interactions": "Interactions",
        "watch_minutes": "Watch and listen minutes",
        "followers": "Followers",
    },
    "nl": {
        "reach": "Bereik",
        "views": "Weergaven",
        "interactions": "Interacties",
        "watch_minutes": "Kijk- en luisterminuten",
        "followers": "Volgers",
    },
}


def _num(v: float, lang: str) -> str:
    s = f"{round(v):,}"
    return s.replace(",", ".") if lang == "nl" else s


def period_label(run: ReportRun, lang: str, tz: ZoneInfo) -> str:
    first = _aware(run.period_start).astimezone(tz).date()
    last = (_aware(run.period_end).astimezone(tz) - timedelta(seconds=1)).date()
    if first == last:
        return first.strftime("%d-%m-%Y") if lang == "nl" else first.isoformat()
    if lang == "nl":
        return f"{first.strftime('%d-%m-%Y')} t/m {last.strftime('%d-%m-%Y')}"
    return f"{first.isoformat()} to {last.isoformat()}"


def recipients(db: Session, report: Report) -> list[str]:
    ids = [int(i) for i in report.recipient_users or []]
    users = db.execute(select(User).where(User.id.in_(ids), User.is_active.is_(True))).scalars() if ids else []
    out: list[str] = []
    for u in users:
        if u.email and u.email.lower() not in out:
            out.append(u.email.lower())
    for e in report.recipient_emails or []:
        if e.lower() not in out:
            out.append(e.lower())
    return out


def editors_ok(db: Session, report: Report) -> bool:
    """A report with the editors ranking may only reach editors-in-chief and administrators."""
    if not has_editors(report):
        return True
    if report.recipient_emails:
        return False
    ids = [int(i) for i in report.recipient_users or []]
    roles = set(db.execute(select(User.role).where(User.id.in_(ids))).scalars()) if ids else set()
    return roles <= set(SEES_EDITORS)


def build_mail(run: ReportRun, token: str, lang: str, tz: ZoneInfo, to: list[str], pdf: bytes | None, app_name: str):
    t = TEXTS.get(lang, TEXTS["en"])
    names = MEASURES.get(lang, MEASURES["en"])
    period = period_label(run, lang, tz)
    url = link(token)
    until = _aware(run.expires_at).astimezone(tz).date()
    until_s = until.strftime("%d-%m-%Y") if lang == "nl" else until.isoformat()
    kpis = []
    for b in (run.data or {}).get("blocks", []):
        blk, data = b.get("block", {}), b.get("data", {})
        if blk.get("type") == "kpi" and "total" in data:
            label = blk.get("title") or names.get(blk.get("measure"), blk.get("measure", ""))
            change = data.get("change")
            kpis.append((label, _num(data["total"] or 0, lang), change))
    esc = html.escape
    rows = "".join(
        f'<td style="padding:12px 16px;border:1px solid #e2e7ef;border-radius:8px">'
        f'<div style="font-size:12px;color:#5d6b80">{esc(label)}</div>'
        f'<div style="font-size:22px;font-weight:700">{value}</div>'
        + (
            f'<div style="font-size:12px;color:{"#0e9f6e" if change >= 0 else "#d64545"}">'
            f"{'▲' if change >= 0 else '▼'} {abs(change):.1f}% {esc(t['vs'])}</div>"
            if change is not None
            else ""
        )
        + "</td>"
        for label, value, change in kpis
    )
    table = f'<table style="border-collapse:separate;border-spacing:8px"><tr>{rows}</tr></table>' if rows else ""
    attach_note = t["pdf"] if pdf else t["nopdf"]
    body_html = (
        '<div style="font-family:Inter,Arial,sans-serif;color:#1d2433;max-width:640px">'
        f'<p style="font-size:12px;color:#5d6b80">{esc(app_name)}</p>'
        f'<h1 style="font-size:20px;margin:0 0 4px">{esc(run.title)}</h1>'
        f'<p style="margin:0 0 16px;color:#5d6b80">{esc(period)}</p>'
        f"<p>{esc(t['intro'].format(period=period))}</p>{table}"
        f'<p style="margin:20px 0"><a href="{esc(url)}" style="background:#0e9f8e;color:#fff;padding:10px 16px;'
        f'border-radius:8px;text-decoration:none;font-weight:600">{esc(t["open"])}</a></p>'
        f'<p style="font-size:12px;color:#5d6b80">{esc(t["until"].format(date=until_s))} {esc(attach_note)}</p>'
        "</div>"
    )
    text_lines = [run.title, period, "", t["intro"].format(period=period)]
    text_lines += [f"{label}: {value}" for label, value, _ in kpis]
    text_lines += ["", f"{t['open']}: {url}", t["until"].format(date=until_s), attach_note]
    filename = f"{run.title} {period}.pdf".replace("/", "-")
    return mail.OutgoingMail(
        to=to,
        subject=t["subject"].format(title=run.title, period=period),
        text="\n".join(text_lines),
        html=body_html,
        attachments=[(filename, "application/pdf", pdf)] if pdf else [],
    )


def send(db: Session, report: Report, run: ReportRun, token: str, to: list[str] | None = None) -> ReportRun:
    """Email a run, one message per recipient so addresses are not shared. Records the outcome."""
    cfg = settings_store.get_section(db, "email")
    tz = org_timezone(db)
    to = to if to is not None else recipients(db, report)
    if not to:
        raise ReportError("no_recipients")
    if not mail.configured(cfg):
        raise ReportError("mail_not_configured")
    pdf = None
    errors: list[str] = []
    if report.attach_pdf:
        try:
            pdf = render_pdf(run, token)
        except ReportError as exc:
            errors.append(str(exc))
    app_name = settings_store.get_section(db, "branding").get("app_name") or "Stats Collector"
    sent: list[str] = []
    for address in to:
        message = build_mail(run, token, report.language, tz, [address], pdf, app_name)
        try:
            try:
                mail.send(cfg, message)
            except mail.MailError as exc:
                if pdf and "attachment_too_large" in str(exc):  # the link still has everything
                    message.attachments = []
                    mail.send(cfg, message)
                else:
                    raise
            sent.append(address)
        except mail.MailError as exc:
            errors.append(f"{address}: {exc}")
    run.recipients = sent
    run.sent_at = utcnow() if sent else None
    run.status = "sent" if sent else "failed"
    run.error = "; ".join(errors)[:500]
    db.commit()
    return run


def run_due(db: Session, now: datetime | None = None) -> int:
    """Generate and send every scheduled report whose time has come."""
    now = now or utcnow()
    tz = org_timezone(db)
    due = db.execute(
        select(Report).where(Report.enabled.is_(True), Report.next_run_at.is_not(None), Report.next_run_at <= now)
    ).scalars()
    n = 0
    for report in list(due):
        report.next_run_at = next_run(report, now, tz)
        db.commit()
        try:
            if not editors_ok(db, report):
                raise ReportError("editors_recipients")
            run, token = generate(db, report, None, "schedule", now)
            send(db, report, run, token)
            n += 1
        except Exception:  # noqa: BLE001 - one report must not stop the others
            log.exception("scheduled report %s failed", report.id)
    return n
