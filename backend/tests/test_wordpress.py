import json
import time
from datetime import UTC, datetime, timedelta

from stats_collector.services import wordpress

PW = "correct horse battery"


def _site(client, csrf):
    r = client.post(
        "/api/sources",
        json={"kind": "wordpress", "name": "Krant", "url": "https://krant.example.org/"},
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["site_key"].startswith("sck_") and body["secret"] and "/api/" not in body["ingest_url"]
    return body


def _push(client, site, payload, secret=None, ts=None):
    raw = json.dumps(payload).encode()
    ts = str(ts or int(time.time()))
    return client.post(
        "/api/ingest/wordpress",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-SC-Key": site["site_key"],
            "X-SC-Timestamp": ts,
            "X-SC-Signature": wordpress.sign(secret or site["secret"], ts, raw),
        },
    )


def _batch(hour: datetime, views=10):
    return {
        "v": 1,
        "site": {"url": "https://krant.example.org", "name": "De Krant", "plugin": "0.3.0", "wp": "6.7"},
        "authors": [
            {"id": 3, "name": "Jan Jansen", "email": "jan@example.org"},
            {"id": 4, "name": "Piet", "email": "piet@example.org"},
        ],
        "items": [
            {
                "id": 101,
                "type": "post",
                "title": "Nieuwe brug geopend",
                "url": "https://krant.example.org/brug",
                "published_at": (hour - timedelta(hours=2)).isoformat(),
                "authors": [3, 4],
                "categories": ["Nieuws"],
                "tags": ["verkeer"],
                "comments": 2,
            }
        ],
        "hours": [
            {"hour": hour.isoformat(), "post": 101, "views": views, "visitors": 8, "read_seconds": 600, "reads": 4},
            {"hour": hour.isoformat(), "post": 0, "views": views + 5, "visitors": 12, "shares": 1},
            {"hour": (hour - timedelta(hours=1)).isoformat(), "post": 101, "views": 3, "visitors": 3},
        ],
        "days": [
            {
                "day": hour.date().isoformat(),
                "post": 0,
                "visitors": 14,
                "referrers": {"google.com": 6, "Facebook.com": 2, "bad domain!": 1},
                "devices": {"mobile": 9, "desktop": 5},
            }
        ],
    }


def test_signature_checks(admin):
    client, csrf = admin
    site = _site(client, csrf)
    assert _push(client, site, {"ping": True}).json() == {"ok": True, "source": "Krant"}
    bad = _push(client, site, {"ping": True}, secret="wrong")
    assert bad.status_code == 401 and bad.json()["error"] == "bad_signature"
    old = _push(client, site, {"ping": True}, ts=int(time.time()) - 3600)
    assert old.status_code == 401 and old.json()["error"] == "clock_skew"
    assert client.post("/api/ingest/wordpress", content=b"{}").json()["error"] == "missing_signature"
    big = client.post("/api/ingest/wordpress", content=b"x" * (wordpress.MAX_BODY + 1))
    assert big.status_code == 413
    # Renewing the key stops the old secret.
    renewed = client.post(f"/api/sources/{site['id']}/rotate-key", headers=csrf).json()
    assert _push(client, site, {"ping": True}).status_code == 401
    assert _push(client, renewed, {"ping": True}).status_code == 200
    listed = client.get("/api/sources").json()[0]
    assert listed["secret"] is None and listed["site_key"] == renewed["site_key"]


def test_ingest_items_people_and_rollups(admin):
    client, csrf = admin
    site = _site(client, csrf)
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    r = _push(client, site, _batch(hour))
    assert r.status_code == 200, r.text
    assert r.json()["hours"] == 3 and r.json()["days"] == 1
    # Same hour again with a higher count replaces the value instead of adding to it.
    assert _push(client, site, _batch(hour, views=20)).status_code == 200

    top = client.get("/api/content/top?range=7d").json()
    assert len(top["items"]) == 1
    item = top["items"][0]
    assert item["title"] == "Nieuwe brug geopend" and item["category"] == "Nieuws"
    assert item["metrics"]["views"] == 23 and item["metrics"]["reads"] == 4
    assert item["avg_read_seconds"] == round(600 / 23, 1)
    assert [a["name"] for a in item["authors"]] == ["Jan Jansen", "Piet"]

    detail = client.get(f"/api/content/{item['id']}?range=7d").json()
    assert sum(detail["series"]["views"]) == 23
    day = client.get(f"/api/content/{item['id']}?range=24h").json()
    assert sum(day["series"]["views"]) == 23 and day["granularity"] == "hour"

    from stats_collector.db import session_factory
    from stats_collector.models import DimensionPoint, MetricPoint

    with session_factory()() as db:
        site_day = {
            m.metric: m.value
            for m in db.query(MetricPoint).filter(MetricPoint.item_id.is_(None), MetricPoint.granularity == "day")
        }
        # Views per day are summed from the hours; unique visitors per day come from the plugin.
        assert site_day["web_views"] == 25 and site_day["web_visitors"] == 14 and site_day["web_shares"] == 1
        months = db.query(MetricPoint).filter(MetricPoint.granularity == "month").count()
        assert months > 0
        dims = {(d.dimension, d.key): d.value for d in db.query(DimensionPoint)}
        assert dims == {
            ("referrer", "google.com"): 6,
            ("referrer", "facebook.com"): 2,
            ("device", "mobile"): 9,
            ("device", "desktop"): 5,
        }

    eds = client.get("/api/editors?range=30d").json()
    assert eds["scope"] == "all" and {e["name"] for e in eds["editors"]} == {"Jan Jansen", "Piet"}
    assert eds["editors"][0]["metrics"]["views"] == 23 and eds["editors"][0]["published"] == 1


def test_editor_sees_only_own_numbers_staff_none(admin):
    client, csrf = admin
    site = _site(client, csrf)
    for email, role in (("jan@example.org", "editor"), ("staff@example.org", "staff")):
        r = client.post(
            "/api/users", json={"email": email, "display_name": email, "role": role, "password": PW}, headers=csrf
        )
        assert r.status_code in (200, 201), r.text
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    assert _push(client, site, _batch(hour)).status_code == 200
    eds = client.get("/api/editors").json()["editors"]
    piet = next(e for e in eds if e["name"] == "Piet")
    jan = next(e for e in eds if e["name"] == "Jan Jansen")
    assert jan["linked_user"] is True and piet["linked_user"] is False

    client.post("/api/auth/logout", headers=csrf)
    assert client.post("/api/auth/login", json={"email": "jan@example.org", "password": PW}).status_code == 200
    own = client.get("/api/editors").json()
    assert own["scope"] == "own" and [e["name"] for e in own["editors"]] == ["Jan Jansen"]
    assert client.get(f"/api/editors/{piet['id']}").status_code == 403
    assert client.get(f"/api/editors/{jan['id']}").status_code == 200
    top = client.get("/api/content/top").json()["items"]
    assert top and "authors" not in top[0]
    assert client.get(f"/api/content/top?person={piet['id']}").status_code == 403
    assert client.get("/api/content/filters").json()["people"] == [{"id": jan["id"], "name": "Jan Jansen"}]

    client.post("/api/auth/logout", headers={})
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "staff@example.org", "password": PW}).status_code == 200
    assert client.get("/api/editors").status_code == 403
    assert client.get("/api/content/filters").json()["people"] == []
    assert "authors" not in client.get("/api/content/top").json()["items"][0]


def test_wrong_ingest_address_is_404(client):
    # A plugin with the full ingest address pasted posts to /api/ingest/wordpress/api/ingest/wordpress.
    r = client.post("/api/ingest/wordpress/api/ingest/wordpress", json={})
    assert r.status_code == 404


def test_plugin_04_extras_and_website_overview(admin):
    client, csrf = admin
    site = _site(client, csrf)
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    batch = _batch(hour)
    batch["items"][0].update(
        {
            "modified_at": hour.isoformat(),
            "words": 750,
            "images": 2,
            "featured_image": True,
            "video": True,
            "revisions": 4,
            "updates": 1,
            "seo": {"plugin": "yoast", "keyword": "brug", "score": 81, "readability": 60},
        }
    )
    batch["days"][0].update(
        {
            "scroll": {"25": 4, "100": 6, "33": 9},
            "campaigns": {"nieuwsbrief|email|week 46": 5, "facebook||": 2, "bad<key": 1},
            "searches": {"Brug  Velsen": 3, "parkeren": 2},
            "searches_empty": {"parkeren": 2},
        }
    )
    batch["days"].append(
        {"day": hour.date().isoformat(), "post": 101, "visitors": 8, "scroll": {"75": 3}, "searches": {"x": 1}}
    )
    batch["live"] = {"readers": 7, "posts": {"101": 4, "999": 1}}
    batch["production"] = {
        "scheduled": 2,
        "drafts": 5,
        "pending": 1,
        "pending_comments": 3,
        "scheduled_items": [{"id": 120, "title": "Morgen", "at": (hour + timedelta(days=1)).isoformat(), "author": 3}],
    }
    r = _push(client, site, batch)
    assert r.status_code == 200, r.text

    item = client.get("/api/content/top?range=7d").json()["items"][0]
    detail = client.get(f"/api/content/{item['id']}?range=7d").json()
    assert detail["readers_now"] == 4
    d = detail["item"]["details"]
    assert d["words"] == 750 and d["video"] is True and d["updates"] == 1 and d["seo"]["score"] == 81
    assert detail["dimensions"]["scroll"] == [{"key": "75", "value": 3.0}]
    assert "search" not in detail["dimensions"]  # searches belong to the site, not an article

    w = client.get("/api/website?range=7d").json()
    assert w["live"]["readers"] == 7 and w["live"]["items"][0]["readers"] == 4
    assert w["searches"]["total"] == 5 and w["searches"]["empty"] == 2
    assert w["searches"]["top"][0] == {"key": "brug velsen", "value": 3.0}
    assert w["searches"]["top_empty"] == [{"key": "parkeren", "value": 2.0}]
    assert w["campaigns"][0] == {"source": "nieuwsbrief", "medium": "email", "campaign": "week 46", "views": 5}
    assert len(w["campaigns"]) == 2
    assert w["scroll"]["views"] == 10 and w["scroll"]["reached"]["100"] == 60.0 and w["scroll"]["reached"]["0"] == 100
    prod = w["production"]
    assert prod["published"] == 1 and prod["updated"] == 1
    assert prod["pipeline"] == {"scheduled": 2, "drafts": 5, "pending": 1, "pending_comments": 3}
    assert prod["scheduled"][0]["title"] == "Morgen" and prod["scheduled"][0]["author"] == "Jan Jansen"
    assert prod["by_editor"] == [{"id": prod["by_editor"][0]["id"], "name": "Jan Jansen", "published": 1}]
    arts = w["articles"]
    assert arts["articles"] == 1 and arts["with_details"] == 1 and arts["avg_words"] == 750
    long_band = next(b for b in arts["length"] if b["key"] == "long")
    assert long_band["items"] == 1 and long_band["avg_views"] == 13
    assert next(b for b in arts["seo"]["bands"] if b["key"] == "good")["items"] == 1

    # Editing the source keeps the snapshots; an old live count is not shown.
    r = client.put(
        f"/api/sources/{site['id']}",
        json={"kind": "wordpress", "name": "Krant", "url": "https://krant.example.org/"},
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    assert client.get("/api/website").json()["production"]["pipeline"]["drafts"] == 5
    from stats_collector.services import website

    later = datetime.now(UTC) + timedelta(minutes=10)
    from stats_collector.db import session_factory

    with session_factory()() as db:
        assert website.live(db, website.sites(db), now=later)["readers"] is None


def test_website_hides_editor_names_from_staff(admin):
    client, csrf = admin
    site = _site(client, csrf)
    client.post(
        "/api/users",
        json={"email": "staff@example.org", "display_name": "S", "role": "staff", "password": PW},
        headers=csrf,
    )
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    batch = _batch(hour)
    batch["production"] = {"scheduled_items": [{"title": "Later", "at": hour.isoformat(), "author": 3}]}
    assert _push(client, site, batch).status_code == 200
    client.post("/api/auth/logout", headers=csrf)
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "staff@example.org", "password": PW}).status_code == 200
    prod = client.get("/api/website").json()["production"]
    assert "by_editor" not in prod and "author" not in prod["scheduled"][0]
