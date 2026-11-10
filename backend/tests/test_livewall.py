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
    assert kinds == {"icecast", "owncast", "wordpress"} and listed["base_url"].endswith(":8081")
    w = client.post("/api/livewalls", json={"name": "Newsroom", "title": "Live now"}, headers=csrf).json()
    token = w["url"].rsplit("/w/", 1)[1]
    assert len(token) >= 30

    wall = _wall_client()
    page = wall.get(f"/w/{token}")
    assert page.status_code == 200 and "Live now" in page.text and "no-store" in page.headers["cache-control"]
    data = wall.get(f"/w/{token}/data").json()
    assert "allow_ips" not in data and {c["kind"] for c in data["channels"]} == kinds
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
