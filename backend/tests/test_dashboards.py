def _demo():
    from stats_collector.db import session_factory
    from stats_collector.services.demo import create_demo

    with session_factory()() as db:
        assert create_demo(db) > 0


def test_data_split_and_compare(admin):
    client, _ = admin
    _demo()
    d = client.get("/api/dashboards/data?measure=reach&range=30d&split=platform").json()
    plat = {s["key"]: s for s in d["series"]}
    assert set(plat) == {"website", "facebook", "instagram"}
    assert len(d["buckets"]) == 30 and all(len(s["values"]) == 30 for s in d["series"])
    assert d["total"] == round(sum(s["total"] for s in d["series"]), 2) and d["total"] > 0
    one = client.get("/api/dashboards/data?measure=reach&range=30d&split=none&platforms=facebook").json()
    assert [s["key"] for s in one["series"]] == ["total"] and one["total"] == plat["facebook"]["total"]

    # Followers: a count per day, also for 24 hours; the total is today's count.
    f = client.get("/api/dashboards/data?measure=followers&range=24h&split=source").json()
    assert (
        f["kind"] == "level"
        and f["granularity"] == "day"
        and f["total"] == 12840 + 6310 + 4870 + 2140 + 980 + 3420 + 5120
    )
    assert all(v is not None for s in f["series"] for v in s["values"][-3:])

    # 24 hours: social media only report days, their hourly values stay empty.
    h = client.get("/api/dashboards/data?measure=views&range=24h&split=source").json()
    assert h["granularity"] == "hour" and h["daily_only"]
    social = [s for s in h["series"] if s["kind"] in ("facebook", "youtube")]
    assert social and all(v is None for s in social for v in s["values"])

    w = client.get("/api/dashboards/data?measure=views&range=7d&compare=true").json()
    assert w["previous"] is not None and w["change"] is not None


def test_crud_and_sharing(admin):
    client, csrf = admin
    _demo()
    listed = client.get("/api/dashboards").json()
    assert [d["name"] for d in listed] == ["Overview"] and listed[0]["shared"] and listed[0]["can_edit"]
    ex = client.post("/api/dashboards/example", headers=csrf).json()
    assert ex["name"] == "Overzicht" and ex["mine"] and not ex["shared"] and len(ex["widgets"]) == 8
    body = {"name": "Mine", "widgets": [{"id": "a", "type": "kpi", "measure": "followers"}]}
    d = client.post("/api/dashboards", json=body, headers=csrf).json()
    assert d["widgets"][0]["size"] == "half" and d["widgets"][0]["split"] == "platform"
    bad = client.post("/api/dashboards", json={**body, "widgets": [{"id": "a", "type": "pie"}]}, headers=csrf)
    assert bad.status_code == 422
    r = client.put(f"/api/dashboards/{d['id']}", json={**body, "name": "Renamed", "shared": True}, headers=csrf)
    assert r.json()["name"] == "Renamed" and r.json()["shared"]

    # Staff: sees shared dashboards, cannot share or change them, keeps their own.
    from sqlalchemy import select

    from stats_collector.db import session_factory
    from stats_collector.models import User

    with session_factory()() as db:
        db.execute(select(User)).scalars().first().role = "staff"
        db.commit()
    assert client.put(f"/api/dashboards/{d['id']}", json=body, headers=csrf).status_code == 200  # still the maker
    shared = next(x for x in client.get("/api/dashboards").json() if x["name"] == "Overview")
    assert not shared["can_edit"]
    assert client.delete(f"/api/dashboards/{shared['id']}", headers=csrf).status_code == 403
    assert client.post("/api/dashboards", json={**body, "shared": True}, headers=csrf).status_code == 403
    assert client.delete(f"/api/dashboards/{d['id']}", headers=csrf).json()["ok"]
