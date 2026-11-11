import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from stats_collector.services import threads

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class Fake:
    """Answers like graph.threads.net for one account with two posts and a repost."""

    def __init__(self):
        self.calls = []
        self.likes = 10
        self.followers = 1000

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = urlparse(str(req.url))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path
        self.calls.append((path, q))
        if path == "/oauth/access_token":
            body = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            assert body["code"] == "good" and body["client_secret"] == "as"
            return httpx.Response(200, json={"access_token": "short", "user_id": "U1"})
        if path == "/access_token":
            assert q["grant_type"] == "th_exchange_token" and q["access_token"] == "short"
            return httpx.Response(200, json={"access_token": "long", "expires_in": 5184000})
        if path == "/refresh_access_token":
            return httpx.Response(200, json={"access_token": "long2", "expires_in": 5184000})
        if q.get("access_token") not in ("long", "long2"):
            return httpx.Response(400, json={"error": {"code": 190, "message": "Invalid token"}})
        if path == "/v1.0/me":
            return httpx.Response(200, json={"id": "U1", "username": "krant"})
        if path == "/v1.0/U1/threads_insights":
            if q["metric"] == "followers_count":
                return httpx.Response(
                    200, json={"data": [{"name": "followers_count", "total_value": {"value": self.followers}}]}
                )
            since = datetime.fromtimestamp(int(q["since"]), UTC).date()
            until = datetime.fromtimestamp(int(q["until"]), UTC).date()
            values = []
            day = since
            while day < until:
                end = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=8)
                values.append({"value": 100, "end_time": end.isoformat().replace("+00:00", "+0000")})
                day += timedelta(days=1)
            return httpx.Response(200, json={"data": [{"name": "views", "period": "day", "values": values}]})
        if path == "/v1.0/U1/threads":
            rows = [
                {
                    "id": "P1",
                    "text": "Lees https://www.krant.nl/a/1 nu",
                    "permalink": "https://www.threads.net/@krant/post/P1",
                    "timestamp": (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "+0000"),
                    "media_type": "TEXT_POST",
                },
                {
                    "id": "P2",
                    "text": "Ouder bericht",
                    "permalink": "https://www.threads.net/@krant/post/P2",
                    "timestamp": (NOW - timedelta(days=3)).isoformat().replace("+00:00", "+0000"),
                    "media_type": "IMAGE",
                    "media_url": "https://cdn/p2.jpg",
                },
                {"id": "R1", "media_type": "REPOST_FACADE", "timestamp": NOW.isoformat()},
            ]
            return httpx.Response(200, json={"data": rows, "paging": {"cursors": {"before": "a", "after": "b"}}})
        if path.endswith("/insights"):
            likes = self.likes if "P1" in path else 3
            data = [
                {"name": name, "values": [{"value": v}]}
                for name, v in (("views", 500), ("likes", likes), ("replies", 2), ("reposts", 1), ("quotes", 0))
            ]
            data.append({"name": "shares", "total_value": {"value": 4}})
            return httpx.Response(200, json={"data": data})
        return httpx.Response(404, json={"error": {"code": 100, "message": "unknown"}})


@pytest.fixture()
def fake(monkeypatch):
    f = Fake()
    client = httpx.Client(transport=httpx.MockTransport(f))
    monkeypatch.setattr(threads, "_client", lambda c=None: c or client)
    from stats_collector import worker

    monkeypatch.setattr(worker, "threads_soon", lambda source_id: None)
    return f


def test_threads_connect_and_sync(admin, fake, api_clock):
    api_clock(NOW + timedelta(hours=4))
    from sqlalchemy import func, select

    from stats_collector.api.threads import STATE_COOKIE
    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem, MetricPoint, Source
    from stats_collector.security import decrypt_secret

    client, csrf = admin
    r = client.post(
        "/api/sources",
        json={"kind": "threads", "name": "Threads", "client_id": "42", "client_secret": "as"},
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["redirect_uri"].endswith("/api/connectors/threads/callback") and not s["connected"]

    bad = client.get("/api/connectors/threads/callback?code=good&state=wrong", follow_redirects=False)
    assert "threads_error=threads_state_invalid" in bad.headers["location"]
    start = client.get(f"/api/connectors/threads/start?source={s['id']}", follow_redirects=False)
    assert start.status_code == 303 and start.headers["location"].startswith("https://threads.net/oauth/authorize?")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    assert "threads_manage_insights" in start.headers["location"]
    assert json.loads(decrypt_secret(client.cookies.get(STATE_COOKIE)))["s"] == state

    back = client.get(f"/api/connectors/threads/callback?code=good%23_&state={state}", follow_redirects=False)
    assert "threads_connected=1" in back.headers["location"], back.headers["location"]
    s = client.get("/api/sources").json()
    s = next(x for x in s if x["kind"] == "threads")
    assert s["connected"] and s["account_name"] == "@krant"

    with session_factory()() as db:
        source = db.get(Source, s["id"])
        assert threads.is_due(source, NOW)
        result = threads.sync(db, source, now=NOW - timedelta(days=1))
        assert result["posts"] == 2  # the repost is skipped
        assert source.config["followers"] == 1000 and not source.config["days_done"]
        for _ in range(2):  # the rest of the two years, 360 days per run
            threads.sync(db, source, now=NOW - timedelta(days=1))
        assert source.config["days_done"] and source.config["history_done"], source.config
        item = db.execute(
            select(ContentItem).where(ContentItem.source_id == source.id, ContentItem.external_id == "P1")
        ).scalar_one()
        assert item.meta["links"] == ["https://www.krant.nl/a/1"]
        # Account views per day back to 13 April 2024, from the insights.
        days = db.execute(
            select(func.count()).where(
                MetricPoint.source_id == source.id,
                MetricPoint.item_id.is_(None),
                MetricPoint.metric == "th_views",
                MetricPoint.granularity == "day",
            )
        ).scalar_one()
        assert days > 500

        fake.likes, fake.followers = 25, 1012
        threads.sync(db, source, now=NOW)
        likes = db.execute(
            select(func.sum(MetricPoint.value)).where(
                MetricPoint.item_id == item.id, MetricPoint.metric == "th_likes", MetricPoint.granularity == "day"
            )
        ).scalar_one()
        assert likes == 25
        follows = db.execute(
            select(func.sum(MetricPoint.value)).where(
                MetricPoint.source_id == source.id, MetricPoint.metric == "th_follows", MetricPoint.granularity == "day"
            )
        ).scalar_one()
        assert follows == 12

    data = client.get("/api/followers?range=30d").json()
    th = next(x for x in data["sources"] if x["kind"] == "threads")
    assert th["current"] == 1012 and th["values"][-2:] == [1000, 1012]

    d = client.post(f"/api/connectors/threads/{s['id']}/disconnect", headers=csrf).json()
    assert not d["connected"] and d["client_secret_set"]


def test_threads_expired_token(admin, fake):
    from stats_collector.connectors import ConnectorError
    from stats_collector.db import session_factory
    from stats_collector.models import Source
    from stats_collector.security import encrypt_secret

    with session_factory()() as db:
        source = Source(
            kind="threads",
            name="T",
            config={"client_id": "42", "account_id": "U1"},
            secret_enc=encrypt_secret(json.dumps({"token": "old", "token_at": NOW.isoformat()})),
        )
        db.add(source)
        db.commit()
        with pytest.raises(ConnectorError):
            threads.sync(db, source, now=NOW)
        assert db.get(Source, source.id).last_error.startswith("threads_reconnect")
