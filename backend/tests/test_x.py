import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from stats_collector.services import xcom

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _post(n, hours_ago, likes, impressions=100):
    return {
        "id": str(1000 + n),
        "text": f"Bericht {n} https://t.co/x",
        "created_at": (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", ".000Z"),
        "public_metrics": {
            "like_count": likes,
            "retweet_count": 2,
            "reply_count": 1,
            "quote_count": 0,
            "bookmark_count": 1,
        },
        "non_public_metrics": {"impression_count": impressions, "url_link_clicks": 7, "user_profile_clicks": 3},
        "entities": {"urls": [{"expanded_url": "https://www.krant.nl/a/1?utm_source=x"}]},
    }


class Fake:
    """Answers like api.x.com for one account."""

    def __init__(self):
        self.calls = []
        self.likes = 10
        self.followers = 2000
        self.refreshes = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = urlparse(str(req.url))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.calls.append((url.path, q))
        if url.path == "/2/oauth2/token":
            body = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            assert req.headers["Authorization"].startswith("Basic ")
            if body["grant_type"] == "authorization_code":
                assert body["code"] == "good" and body["code_verifier"]
            else:
                self.refreshes += 1
                if body["refresh_token"] == "dead":
                    return httpx.Response(400, json={"error": "invalid_request", "error_description": "invalid_grant"})
            n = self.refreshes
            return httpx.Response(
                200,
                json={"access_token": f"at{n}", "refresh_token": f"rt{n}", "expires_in": 7200, "token_type": "bearer"},
            )
        if not req.headers.get("Authorization", "").startswith("Bearer at"):
            return httpx.Response(401, json={"title": "Unauthorized"})
        if url.path == "/2/users/me":
            return httpx.Response(
                200,
                json={"data": {"id": "U1", "username": "krant", "public_metrics": {"followers_count": self.followers}}},
            )
        if url.path == "/2/users/U1/tweets":
            if "start_time" in q:
                return httpx.Response(200, json={"data": [_post(1, 2, self.likes), _post(2, 50, 3)], "meta": {}})
            return httpx.Response(200, json={"data": [_post(3, 24 * 40, 9)], "meta": {}})  # history
        return httpx.Response(404, json={})


@pytest.fixture()
def fake(monkeypatch):
    f = Fake()
    client = httpx.Client(transport=httpx.MockTransport(f))
    monkeypatch.setattr(xcom, "_client", lambda c=None: c or client)
    from stats_collector import worker

    monkeypatch.setattr(worker, "x_soon", lambda source_id: None)
    return f


def _create(client, csrf, **extra):
    body = {"kind": "x", "name": "X", "client_id": "cid", "client_secret": "sec", **extra}
    r = client.post("/api/sources", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    return r.json()


def test_x_connect_sync_and_budget(admin, fake):
    from sqlalchemy import func, select

    from stats_collector.api.xcom import STATE_COOKIE
    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem, MetricPoint, Source
    from stats_collector.security import decrypt_secret, encrypt_secret

    client, csrf = admin
    s = _create(client, csrf, budget_usd=5)
    assert s["budget_usd"] == 5 and s["every_hours"] == 6 and s["redirect_uri"].endswith("/api/connectors/x/callback")
    start = client.get(f"/api/connectors/x/start?source={s['id']}", follow_redirects=False)
    loc = start.headers["location"]
    assert loc.startswith("https://x.com/i/oauth2/authorize?") and "code_challenge_method=S256" in loc
    assert "offline.access" in parse_qs(urlparse(loc).query)["scope"][0]
    state = json.loads(decrypt_secret(client.cookies.get(STATE_COOKIE)))["s"]
    back = client.get(f"/api/connectors/x/callback?code=good&state={state}", follow_redirects=False)
    assert "x_connected=1" in back.headers["location"], back.headers["location"]
    s = next(x for x in client.get("/api/sources").json() if x["kind"] == "x")
    assert s["connected"] and s["account_name"] == "@krant" and s["followers"] == 2000

    with session_factory()() as db:
        source = db.get(Source, s["id"])
        assert xcom.is_due(source, NOW)
        values = json.loads(decrypt_secret(source.secret_enc))
        source.secret_enc = encrypt_secret(json.dumps({**values, "expires_at": (NOW - timedelta(days=2)).isoformat()}))
        db.commit()
        result = xcom.sync(db, source, now=NOW - timedelta(days=1))
        assert result["posts"] == 3 and source.config["history_done"]  # the week plus the history
        assert fake.refreshes == 1  # the first access token had run out by then
        # Three posts and two user reads (connect and sync) so far.
        usage = source.config["usage"]
        assert usage["posts"] == 3 and usage["users"] == 2
        item = db.execute(
            select(ContentItem).where(ContentItem.source_id == source.id, ContentItem.external_id == "1001")
        ).scalar_one()
        assert item.url == "https://x.com/krant/status/1001"
        assert item.meta["links"] == ["https://www.krant.nl/a/1?utm_source=x"]

        fake.likes, fake.followers = 30, 2015
        assert not xcom.is_due(source, NOW - timedelta(hours=20))  # every 6 hours
        xcom.sync(db, source, now=NOW)
        likes = db.execute(
            select(func.sum(MetricPoint.value)).where(
                MetricPoint.item_id == item.id, MetricPoint.metric == "x_likes", MetricPoint.granularity == "day"
            )
        ).scalar_one()
        assert likes == 30
        follows = db.execute(
            select(func.sum(MetricPoint.value)).where(
                MetricPoint.source_id == source.id, MetricPoint.metric == "x_follows", MetricPoint.granularity == "day"
            )
        ).scalar_one()
        assert follows == 15

        # The budget: once it is spent, nothing more is read this month.
        source.config = {**source.config, "usage": {"month": "2026-11", "usd": 5.0, "posts": 1000, "users": 3}}
        db.commit()
        assert not xcom.is_due(source, NOW + timedelta(hours=7))
        calls = len(fake.calls)
        with pytest.raises(Exception, match="x_budget_reached"):
            xcom.sync(db, source, now=NOW + timedelta(hours=7))
        assert len(fake.calls) == calls + 1  # only the token refresh, no paid reads
        assert db.get(Source, source.id).last_error == "x_budget_reached"
        # A new month starts with a clean slate.
        assert xcom.is_due(db.get(Source, source.id), datetime(2026, 12, 1, 1, tzinfo=UTC))

    shown = next(x for x in client.get("/api/sources").json() if x["kind"] == "x")
    assert shown["spent_usd"] == 5.0
    d = client.post(f"/api/connectors/x/{s['id']}/disconnect", headers=csrf).json()
    assert not d["connected"] and d["client_secret_set"]


def test_x_refresh_token_revoked(admin, fake):
    from stats_collector.connectors import ConnectorError
    from stats_collector.db import session_factory
    from stats_collector.models import Source
    from stats_collector.security import encrypt_secret

    with session_factory()() as db:
        source = Source(
            kind="x",
            name="X",
            config={"client_id": "cid", "account_id": "U1"},
            secret_enc=encrypt_secret(json.dumps({"client_secret": "sec", "refresh_token": "dead"})),
        )
        db.add(source)
        db.commit()
        with pytest.raises(ConnectorError):
            xcom.sync(db, source, now=NOW)
        assert db.get(Source, source.id).last_error == "x_reconnect"
