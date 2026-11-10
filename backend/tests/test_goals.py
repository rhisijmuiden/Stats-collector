from datetime import date, datetime, timedelta

from stats_collector.services import goals


def _demo():
    from stats_collector.db import session_factory
    from stats_collector.services.demo import create_demo

    with session_factory()() as db:
        assert create_demo(db) > 0


def _source(client, kind):
    return next(s for s in client.get("/api/sources").json() if s["kind"] == kind)


def test_followers(admin):
    client, _ = admin
    _demo()
    data = client.get("/api/followers?range=30d").json()
    kinds = {s["kind"]: s for s in data["sources"]}
    assert set(kinds) == {"youtube", "facebook", "instagram", "bluesky", "mastodon"}
    assert kinds["facebook"]["current"] == 12840 and kinds["facebook"]["values"][-1] == 12840
    assert len(data["days"]) == 30 and data["total"] == 12840 + 6310 + 4870 + 2140 + 980
    assert data["total_values"][-1] == data["total"]
    assert kinds["instagram"]["change"] > 0 and kinds["instagram"]["gained"] > 0


def test_goal_level_and_revisions(admin):
    client, csrf = admin
    _demo()
    fb = _source(client, "facebook")
    today = date.today()
    body = {
        "name": "Facebook 15k",
        "metric": "followers",
        "source_ids": [fb["id"]],
        "target": 15000,
        "start_date": (today - timedelta(days=20)).isoformat(),
        "end_date": (today + timedelta(days=40)).isoformat(),
        "notify": True,
    }
    r = client.post("/api/goals", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["kind"] == "level" and g["current"] == 12840 and g["baseline"] < 12840
    assert 0 < g["progress"] < 100 and g["status"] in ("on_track", "behind") and len(g["revisions"]) == 1
    assert g["values"][-1] == 12840 and set(g["targets"]) == {15000}

    # Lower the target: it is reached, and the old target stays in the history.
    r = client.put(f"/api/goals/{g['id']}", json={**body, "target": 12000, "note": "more realistic"}, headers=csrf)
    g = r.json()
    assert g["status"] == "reached" and g["progress"] == 100
    assert [x["target"] for x in g["revisions"]] == [15000, 12000] and g["revisions"][1]["note"] == "more realistic"
    listed = next(x for x in client.get("/api/goals").json() if x["id"] == g["id"])
    assert "days" not in listed and listed["spark"]


def test_goal_total_and_permissions(admin, client):
    client_, csrf = admin
    _demo()
    today = date.today()
    body = {
        "name": "Reach this month",
        "metric": "reach",
        "target": 10_000_000,
        "start_date": (today - timedelta(days=10)).isoformat(),
        "end_date": (today + timedelta(days=20)).isoformat(),
    }
    g = client_.post("/api/goals", json=body, headers=csrf).json()
    assert g["kind"] == "total" and g["values"] == sorted(g["values"]) and g["current"] > 0
    assert g["status"] == "behind" and g["needed_per_day"] > g["rate_per_day"]
    assert client_.post("/api/goals", json={**body, "end_date": body["start_date"]}, headers=csrf).status_code == 422
    assert client_.post("/api/goals", json={**body, "source_ids": [999]}, headers=csrf).status_code == 400

    from stats_collector.db import session_factory
    from stats_collector.models import Goal

    sent = []
    import stats_collector.services.mail as mail

    with session_factory()() as db:
        from stats_collector.services import settings_store

        settings_store.set_section(db, "email", {**settings_store.get_section(db, "email"), "host": "smtp.test"})
        goal = db.get(Goal, g["id"])
        goal.notify = True
        db.commit()
        orig = mail.send
        mail.send = lambda cfg, m: sent.append(m)
        try:
            assert goals.check(db, datetime.now().astimezone()) == 1
            assert goals.check(db, datetime.now().astimezone()) == 0  # once a week at most
        finally:
            mail.send = orig
    assert "achter" in sent[0].subject  # the admin's language is Dutch
