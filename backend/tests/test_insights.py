"""Alerts on outliers, best posting times, stories, weekly editor summaries and recurring goals."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 11, 11, 14, 5, tzinfo=UTC)  # a Wednesday


def _db():
    from stats_collector.db import session_factory

    return session_factory()()


def _day(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), TZ).astimezone(UTC)


def _site(db, kind="wordpress", name="Site"):
    from stats_collector.models import Source

    s = Source(kind=kind, name=name, config={})
    db.add(s)
    db.flush()
    return s


def _item(db, source, n, published, views, metric="web_views", title=None, url=None):
    """An item with its views spread over its first two days."""
    from stats_collector.models import ContentItem, MetricPoint

    kind = "article" if source.kind == "wordpress" else "post"
    item = ContentItem(
        source_id=source.id, kind=kind, external_id=str(n), title=title or f"Item {n}", url=url, published_at=published
    )
    db.add(item)
    db.flush()
    first = published.astimezone(TZ).date()
    for k, share in ((0, 0.7), (1, 0.3)):
        db.add(
            MetricPoint(
                source_id=source.id,
                item_id=item.id,
                metric=metric,
                granularity="day",
                bucket=_day(first + timedelta(days=k)),
                value=views * share,
            )
        )
    return item


# ----------------------------------------------------------------------------- best times


def test_best_times(admin):
    client, _ = admin
    db = _db()
    site = _site(db)
    n = 0
    for week in range(1, 9):
        base = _day(NOW.astimezone(TZ).date() - timedelta(weeks=week))
        # Tuesday 07:00 local always does well, Friday 22:00 badly.
        tue = base - timedelta(days=1) + timedelta(hours=7)
        fri = base + timedelta(days=2, hours=22)
        for when, views in ((tue, 900), (fri, 100)):
            n += 1
            _item(db, site, n, when, views)
    db.commit()
    from stats_collector.services.besttimes import best_times

    data = best_times(db, site, 90, now=NOW)
    assert data["items"] == 16 and data["measure"] == "views"
    best = data["best"][0]
    assert (best["weekday"], best["hour"]) == (1, 7) and best["avg"] == 900 and best["index"] > 100
    assert data["by_day"][4]["avg"] == 100
    r = client.get(f"/api/best-times?source_id={site.id}&days=90")
    assert r.status_code == 200 and r.json()["source"]["name"] == "Site"
    assert client.get("/api/best-times?source_id=999").status_code == 404
    db.close()


# ----------------------------------------------------------------------------- alerts


def test_item_alert_teams_and_once(admin, monkeypatch):
    client, csrf = admin
    db = _db()
    site = _site(db)
    for n in range(10):
        _item(db, site, n, NOW - timedelta(days=5 + n), 100 + n)
    hot = _item(db, site, 99, NOW - timedelta(hours=10), 2000, title="Bridge closed", url="https://example.org/bridge")
    _item(db, site, 98, NOW - timedelta(hours=8), 150)
    db.commit()

    sent = []
    from stats_collector.services import alerts

    monkeypatch.setattr(alerts, "send_teams", lambda url, payload: sent.append((url, payload)))
    body = {
        "name": "Stories going hard",
        "scope": "item",
        "factor": 3,
        "min_value": 500,
        "teams_webhook": "https://example.webhook.office.com/hook",
        "language": "nl",
    }
    assert client.post("/api/alerts", json={**body, "teams_webhook": "http://x"}, headers=csrf).status_code == 422
    r = client.post("/api/alerts", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["teams_webhook_set"] and "teams_webhook" not in rule

    assert alerts.check(db, now=NOW) == 1
    assert len(sent) == 1
    url, payload = sent[0]
    card = payload["attachments"][0]["content"]
    assert url.endswith("/hook") and "Bridge closed" in card["body"][0]["text"]
    assert "weergaven" in card["body"][1]["text"] and card["actions"][0]["url"] == "https://example.org/bridge"
    assert alerts.check(db, now=NOW + timedelta(minutes=15)) == 0  # reported once

    data = client.get("/api/alerts").json()
    assert data["rules"][0]["alerts_7d"] == 1
    event = data["events"][0]
    assert event["item_id"] == hot.id and event["delivered"] == ["teams"] and event["factor"] > 3

    # Keeping the stored webhook when the field is left empty; "-" removes it.
    r = client.put(f"/api/alerts/{rule['id']}", json={**body, "teams_webhook": ""}, headers=csrf)
    assert r.json()["teams_webhook_set"]
    r = client.put(f"/api/alerts/{rule['id']}", json={**body, "teams_webhook": "-"}, headers=csrf)
    assert not r.json()["teams_webhook_set"]
    assert client.post(f"/api/alerts/{rule['id']}/test", headers=csrf).status_code == 400
    db.close()


def test_channel_alert_and_quiet_hours(admin, monkeypatch):
    from stats_collector.models import AlertRule, MetricPoint
    from stats_collector.services import alerts

    db = _db()
    site = _site(db)
    hour = NOW.replace(minute=0) - timedelta(hours=1)
    for w in range(1, 5):
        db.add(
            MetricPoint(
                source_id=site.id, metric="web_views", granularity="hour", bucket=hour - timedelta(weeks=w), value=200
            )
        )
    db.add(MetricPoint(source_id=site.id, metric="web_views", granularity="hour", bucket=hour, value=900))
    rule = AlertRule(name="Busy", scope="channel", factor=3, min_value=100, emails=["desk@example.org"], language="en")
    db.add(rule)
    db.commit()

    mails = []
    monkeypatch.setattr(alerts.mail, "configured", lambda cfg: True)
    monkeypatch.setattr(alerts.mail, "send", lambda cfg, m: mails.append(m))

    rule.quiet_start, rule.quiet_end = "14:00", "16:00"  # 15:05 in Amsterdam
    db.commit()
    assert alerts.check(db, now=NOW) == 0 and not mails
    rule.quiet_start = rule.quiet_end = ""
    db.commit()
    assert alerts.check(db, now=NOW) == 1
    assert mails[0].to == ["desk@example.org"] and "busier than usual" in mails[0].subject
    assert "4.5×" in mails[0].text and "between 14:00 and 15:00" in mails[0].text
    db.close()


# ----------------------------------------------------------------------------- stories


def test_story_over_channels(admin):
    client, csrf = admin
    from stats_collector.models import ItemLink, StreamSample

    db = _db()
    site = _site(db)
    fb = _site(db, "facebook", "FB")
    radio = _site(db, "icecast", "Radio")
    today = date.today()
    published = _day(today - timedelta(days=1)) + timedelta(hours=9)
    article = _item(db, site, 1, published, 1000, title="Storm hits the harbour")
    post = _item(db, fb, 2, published, 500, metric="fb_views", title="Look at this")
    other = _item(db, fb, 3, published, 300, metric="fb_views", title="Storm damage photos")
    _item(db, site, 4, published, 50, title="Unrelated")
    db.add(ItemLink(from_item_id=post.id, to_item_id=article.id, method="url"))
    slot_start = published + timedelta(hours=1)
    for m in range(0, 30, 1):
        db.add(StreamSample(source_id=radio.id, ts=slot_start + timedelta(minutes=m), value=40 + (m % 3), online=True))
    db.commit()

    body = {
        "name": "Storm",
        "item_ids": [article.id],
        "keywords": ["storm", "x"],
        "radio": [
            {
                "source_id": radio.id,
                "start": slot_start.isoformat(),
                "end": (slot_start + timedelta(minutes=30)).isoformat(),
                "label": "Interview",
            }
        ],
        "start_date": (today - timedelta(days=2)).isoformat(),
    }
    assert client.post("/api/stories", json={**body, "item_ids": [9999]}, headers=csrf).status_code == 400
    assert (
        client.post(
            "/api/stories", json={**body, "radio": [{**body["radio"][0], "source_id": site.id}]}, headers=csrf
        ).status_code
        == 400
    )
    r = client.post("/api/stories", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["keywords"] == ["storm"]
    why = {i["id"]: i["why"] for i in s["items"]}
    assert why == {article.id: "picked", post.id: "linked", other.id: "keyword"}
    channels = {c["platform"]: c for c in s["channels"]}
    assert channels["website"]["views"] == 1000 and channels["facebook"]["views"] == 800
    assert channels["icecast"]["listener_minutes"] == s["radio"][0]["listener_minutes"] > 1000
    assert s["radio"][0]["peak"] == 42 and s["totals"]["views"] == 1800
    assert sum(s["series"]["website"]["views"]) == 1000

    # Leave the keyword match out by hand.
    r = client.put(f"/api/stories/{s['id']}", json={**body, "excluded_ids": [other.id]}, headers=csrf)
    assert other.id not in {i["id"] for i in r.json()["items"]}
    listed = client.get("/api/stories").json()
    assert listed[0]["totals"]["views"] == 1500 and "items" not in listed[0]
    assert client.delete(f"/api/stories/{s['id']}", headers=csrf).json() == {"ok": True}
    db.close()


# ----------------------------------------------------------------------------- weekly summary


def test_weekly_summary(admin):
    client, csrf = admin
    from stats_collector.models import ItemPerson, Person
    from stats_collector.services import digest

    db = _db()
    site = _site(db)
    anne = Person(display_name="Anne", email="anne@example.org")
    bob = Person(display_name="Bob", email=None)
    db.add_all([anne, bob])
    db.flush()
    monday = NOW.astimezone(TZ).date() - timedelta(days=NOW.astimezone(TZ).weekday() + 7)
    for n, (person, views) in enumerate([(anne, 800), (anne, 400), (bob, 2000)]):
        item = _item(db, site, n, _day(monday + timedelta(days=1)) + timedelta(hours=8), views, title=f"Story {n}")
        db.add(ItemPerson(item_id=item.id, person_id=person.id, role="author"))
    db.commit()

    data = digest.editor_week(db, anne, NOW)
    assert data["views"] == 1200 and data["published"] == 2 and data["rank"] == 2 and data["editors"] == 2
    assert [b["title"] for b in data["best"]] == ["Story 0", "Story 1"]

    r = client.put("/api/digest", json={"enabled": True, "weekday": 2, "time": "15:00", "ranking": True}, headers=csrf)
    assert r.status_code == 200, r.text
    editors = {e["name"]: e for e in r.json()["editors"]}
    assert editors["Anne"]["email"] == "anne@example.org" and editors["Bob"]["email"] is None
    preview = client.get(f"/api/digest/preview/{anne.id}").json()
    assert "Anne" in preview["html"] and preview["language"] in ("en", "nl")

    assert preview["to"] == "anne@example.org" and preview["subject"]
    db.close()


def test_weekly_summary_schedule(admin, monkeypatch):
    from stats_collector.models import ItemPerson, Person
    from stats_collector.services import digest, settings_store

    db = _db()
    site = _site(db)
    anne = Person(display_name="Anne", email="anne@example.org")
    db.add(anne)
    db.flush()
    monday = NOW.astimezone(TZ).date() - timedelta(days=NOW.astimezone(TZ).weekday() + 7)
    item = _item(db, site, 1, _day(monday) + timedelta(hours=8), 500)
    db.add(ItemPerson(item_id=item.id, person_id=anne.id, role="author"))
    db.commit()
    settings_store.update_section(db, "digest", {"enabled": True, "weekday": 2, "time": "16:00"})
    mails = []
    monkeypatch.setattr(digest.mail, "configured", lambda cfg: True)
    monkeypatch.setattr(digest.mail, "send", lambda cfg, m: mails.append(m))
    assert digest.run_due(db, NOW) == 0  # 15:05 local: not yet
    later = NOW + timedelta(hours=1)
    assert digest.run_due(db, later) == 1 and mails[0].to == ["anne@example.org"]
    assert "2-11 t/m 8-11-2026" in mails[0].subject and "500" in mails[0].text
    assert digest.run_due(db, later + timedelta(minutes=10)) == 0  # once a week
    settings_store.update_section(db, "digest", {"excluded_person_ids": [anne.id], "last_week": ""})
    assert digest.run_due(db, later + timedelta(minutes=20)) == 0
    db.close()


# ----------------------------------------------------------------------------- recurring goals


@pytest.mark.parametrize("period", ["week", "month"])
def test_recurring_goal(admin, period):
    from stats_collector.models import Goal, MetricPoint
    from stats_collector.services import goals

    db = _db()
    fb = _site(db, "facebook", "FB")
    today = NOW.astimezone(TZ).date()
    for k in range(70):
        d = today - timedelta(days=k)
        db.add(MetricPoint(source_id=fb.id, metric="fb_views", granularity="day", bucket=_day(d), value=100))
        db.add(
            MetricPoint(source_id=fb.id, metric="fb_followers", granularity="day", bucket=_day(d), value=5000 - 10 * k)
        )
    views = Goal(
        name="Views",
        metric="views",
        source_ids=[fb.id],
        target=400,
        period=period,
        start_date=today - timedelta(days=60),
    )
    followers = Goal(
        name="Growth",
        metric="followers",
        source_ids=[fb.id],
        target=50,
        period=period,
        start_date=today - timedelta(days=60),
    )
    db.add_all([views, followers])
    db.commit()
    first = today - timedelta(days=today.weekday()) if period == "week" else today.replace(day=1)
    days = (today - first).days + 1
    p = goals.progress(db, views, NOW)
    assert p["period_start"] == first.isoformat() and p["current"] == 100 * days
    f = goals.progress(db, followers, NOW)
    assert f["current"] == 10 * days and f["baseline"] == 0
    hist = goals.history(db, views, today, TZ)
    assert hist and all(h["reached"] for h in hist) and hist[0]["end"] == (first - timedelta(days=1)).isoformat()
    db.close()
