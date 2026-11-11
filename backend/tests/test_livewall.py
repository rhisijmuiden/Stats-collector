from datetime import timedelta

import pytest


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    """Tests use the file store; no worker: walls refresh inline."""
    from stats_collector import worker
    from stats_collector.services import livewall

    monkeypatch.setattr(livewall, "_redis", lambda: None)
    monkeypatch.setattr(worker, "livewall_soon", lambda: worker.livewall_task())


def _demo():
    from stats_collector.db import session_factory
    from stats_collector.services.demo import create_demo

    with session_factory()() as db:
        assert create_demo(db) > 0


def _wall_client():
    from fastapi.testclient import TestClient

    from stats_collector.livewall.app import create_app

    return TestClient(create_app())


def test_wall_lifecycle(admin):
    client, csrf = admin
    _demo()
    listed = client.get("/api/livewalls").json()
    kinds = {s["kind"] for s in listed["sources"]}
    assert {"icecast", "owncast", "wordpress", "facebook", "youtube"} <= kinds and listed["base_url"].endswith(":8081")
    w = client.post("/api/livewalls", json={"name": "Newsroom", "title": "Live now"}, headers=csrf).json()
    assert w["layout"] == "rotate" and w["rotate_seconds"] == 30 and w["show_authors"]
    token = w["url"].rsplit("/w/", 1)[1]
    assert len(token) >= 30

    wall = _wall_client()
    page = wall.get(f"/w/{token}")
    assert page.status_code == 200 and "Live now" in page.text and "no-store" in page.headers["cache-control"]
    data = wall.get(f"/w/{token}/data").json()
    assert "allow_ips" not in data and {c["kind"] for c in data["channels"]} == {"icecast", "owncast", "wordpress"}
    assert {s["kind"] for s in data["socials"]} == kinds - {"icecast", "owncast", "wordpress"}
    fb = next(s for s in data["socials"] if s["kind"] == "facebook")
    assert len(fb["days"]) == 7 and fb["measure"] == "views" and fb["followers"] and fb["goal"]["target"] == 13500
    assert data["totals"]["views_yesterday"] > 0 and len(data["totals"]["views_days"]) == 7
    assert data["top"] and data["top"][0]["value"] >= data["top"][-1]["value"] and data["layout"] == "rotate"
    assert any(t["author"] for t in data["top"]) and {g["name"] for g in data["goals"]} >= {"13,500 Facebook followers"}
    radio = next(c for c in data["channels"] if c["kind"] == "icecast")
    assert len(radio["bars"]) == 12 and radio["unit"] == "listeners" and any(radio["bars"])
    assert wall.get("/w/" + "x" * 32).status_code == 404 and wall.get("/w/short").status_code == 404

    # Only some channels, and only from one network.
    site = next(s for s in listed["sources"] if s["kind"] == "wordpress")
    body = {"name": "Newsroom", "source_ids": [site["id"]], "allow_ips": "10.0.0.0/8"}
    assert client.put(f"/api/livewalls/{w['id']}", json=body, headers=csrf).status_code == 200
    assert wall.get(f"/w/{token}/data").status_code == 403  # the test client is not in 10.0.0.0/8
    bad = client.put(f"/api/livewalls/{w['id']}", json={**body, "allow_ips": "nonsense"}, headers=csrf)
    assert bad.status_code == 422
    body["allow_ips"] = ""
    client.put(f"/api/livewalls/{w['id']}", json=body, headers=csrf)
    assert [c["kind"] for c in wall.get(f"/w/{token}/data").json()["channels"]] == ["wordpress"]

    # A new link: the old one stops working at once.
    new = client.post(f"/api/livewalls/{w['id']}/rotate", headers=csrf).json()
    assert new["url"] != w["url"] and wall.get(f"/w/{token}").status_code == 404
    new_token = new["url"].rsplit("/w/", 1)[1]
    assert wall.get(f"/w/{new_token}/data").status_code == 200

    # Switched off, then deleted.
    client.put(f"/api/livewalls/{w['id']}", json={**body, "enabled": False}, headers=csrf)
    assert wall.get(f"/w/{new_token}/data").status_code == 404
    assert client.delete(f"/api/livewalls/{w['id']}", headers=csrf).json()["ok"]
    assert [x["name"] for x in client.get("/api/livewalls").json()["walls"]] == ["Newsroom"]  # the demo wall


def test_website_views_per_minute(app_env):
    """Views per minute come from the change in today's total between two runs."""
    from stats_collector.db import session_factory
    from stats_collector.models import MetricPoint, Source, utcnow
    from stats_collector.services import livewall
    from stats_collector.services.rollup import hour_floor

    livewall._redis = lambda: None
    with session_factory()() as db:
        site = Source(kind="wordpress", name="Site", config={})
        db.add(site)
        db.flush()
        now = utcnow().replace(second=30, microsecond=0)
        hour = hour_floor(now)
        point = MetricPoint(
            source_id=site.id, item_id=None, granularity="hour", bucket=hour, metric="web_views", value=100
        )
        db.add(point)
        db.commit()
        assert livewall.website_minutes(db, site, now) == []  # first run: only the starting total
        point.value = 130
        db.commit()
        later = now + timedelta(minutes=1)
        assert livewall.website_minutes(db, site, later) == [(later.replace(second=0).isoformat(), 30.0)]
        assert len(livewall.website_minutes(db, site, later)) == 1  # the same minute again adds nothing


def test_rate_limit():
    from stats_collector.livewall.app import RateLimiter

    r = RateLimiter(per_minute=3)
    assert [r.allow("a") for _ in range(4)] == [True, True, True, False] and r.allow("b")


def test_wall_address_and_proxy(admin):
    import asyncio

    from stats_collector.livewall.app import WallProxyHeaders

    client, csrf = admin
    assert client.get("/api/livewalls/config").json()["public_url"] == ""
    bad = client.put("/api/livewalls/config", json={"public_url": "wall.example.org"}, headers=csrf)
    assert bad.status_code == 422
    bad = client.put("/api/livewalls/config", json={"trusted_proxies": "nonsense"}, headers=csrf)
    assert bad.status_code == 422
    body = {"public_url": "https://wall.example.org/", "trusted_proxies": "192.0.2.5"}
    cfg = client.put("/api/livewalls/config", json=body, headers=csrf).json()
    assert cfg["public_url"] == "https://wall.example.org" and cfg["trusted_proxies"] == "192.0.2.5"
    w = client.post("/api/livewalls", json={"name": "Hall"}, headers=csrf).json()
    assert w["url"].startswith("https://wall.example.org/w/")
    assert client.get("/api/livewalls").json()["base_url"] == "https://wall.example.org"

    # The wall service trusts the proxy set here (handed over by the worker), next to the config file.
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    mw = WallProxyHeaders(app, "127.0.0.1")
    scope = {"type": "http", "client": ("192.0.2.5", 1), "headers": [(b"x-forwarded-for", b"198.51.100.7")]}
    asyncio.run(mw(scope, None, None))
    assert seen["client"] == "198.51.100.7"
    asyncio.run(mw({**scope, "client": ("203.0.113.9", 1)}, None, None))
    assert seen["client"] == "203.0.113.9"  # not a trusted proxy: the header is ignored


def test_wall_layout_and_rising(admin):
    """Layout options, editor names switched off, and views gained since an earlier run."""
    from datetime import UTC, datetime

    from stats_collector.db import session_factory
    from stats_collector.models import LiveWall
    from stats_collector.services import livewall

    client, csrf = admin
    _demo()
    w = client.post(
        "/api/livewalls",
        json={"name": "Hall", "layout": "stories", "rotate_seconds": 45, "show_authors": False},
        headers=csrf,
    ).json()
    assert (w["layout"], w["rotate_seconds"], w["show_authors"]) == ("stories", 45, False)
    bad = client.put(f"/api/livewalls/{w['id']}", json={"name": "Hall", "rotate_seconds": 5}, headers=csrf)
    assert bad.status_code == 422
    snap = client.get(f"/api/livewalls/{w['id']}/preview").json()
    assert snap["layout"] == "stories" and snap["rotate_seconds"] == 45
    assert snap["top"] and not any(t["author"] for t in snap["top"])

    with session_factory()() as db:
        wall = db.get(LiveWall, w["id"])
        now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
        top = [{"id": 1, "value": 100}, {"id": 2, "value": 50}]
        assert livewall._rising(wall, top, "d", now) == []
        later = [{"id": 1, "value": 160}, {"id": 2, "value": 50}]
        assert livewall._rising(wall, later, "d", now + timedelta(minutes=10)) == [{"id": 1, "value": 160, "gain": 60}]
        assert livewall._rising(wall, later, "next-day", now + timedelta(minutes=11)) == []
