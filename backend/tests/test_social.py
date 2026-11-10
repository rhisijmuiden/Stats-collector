from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from stats_collector.services import social

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
DID = "did:plc:abc123"


def _bsky_post(n, days_ago, likes, text="Hello", link=None):
    created = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    post = {
        "uri": f"at://{DID}/app.bsky.feed.post/r{n}",
        "author": {"did": DID, "handle": "krant.bsky.social"},
        "record": {"text": text, "createdAt": created},
        "likeCount": likes,
        "repostCount": 2,
        "replyCount": 1,
        "quoteCount": 0,
    }
    if link:
        post["embed"] = {"$type": "app.bsky.embed.external#view", "external": {"uri": link, "thumb": "https://t/1.jpg"}}
    return {"post": post}


class Fake:
    """Answers like the Bluesky AppView and a Mastodon server."""

    def __init__(self):
        self.followers = 500
        self.likes = 10
        self.calls = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = urlparse(str(req.url))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.calls.append((url.netloc, url.path, q))
        if url.path.endswith("app.bsky.actor.getProfile"):
            if q["actor"] != "krant.bsky.social":
                return httpx.Response(400, json={"error": "InvalidRequest"})
            return httpx.Response(
                200,
                json={
                    "did": DID,
                    "handle": "krant.bsky.social",
                    "displayName": "Krant",
                    "followersCount": self.followers,
                },
            )
        if url.path.endswith("app.bsky.feed.getAuthorFeed"):
            if q.get("cursor") == "page2":
                return httpx.Response(200, json={"feed": [_bsky_post(3, 400, 99)]})  # older than a year
            feed = [
                _bsky_post(1, 0, self.likes, "Nieuw artikel", "https://www.krant.nl/a/1?utm_source=bsky"),
                {"post": {**_bsky_post(9, 0, 5)["post"], "author": {"did": "did:plc:other"}}, "reason": {}},
                _bsky_post(2, 40, 7),
            ]
            return httpx.Response(200, json={"feed": feed, "cursor": "page2"})
        if url.netloc == "social.example":
            if req.headers.get("Authorization") != "Bearer tok":
                return httpx.Response(401, json={"error": "This method requires an authenticated user"})
            if url.path == "/api/v1/accounts/lookup":
                return httpx.Response(
                    200,
                    json={
                        "id": "77",
                        "username": "krant",
                        "acct": "krant",
                        "display_name": "De Krant",
                        "url": "https://social.example/@krant",
                        "followers_count": self.followers,
                        "statuses_count": 3,
                    },
                )
            if url.path == "/api/v1/accounts/77/statuses":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "1001",
                            "created_at": (NOW - timedelta(hours=3)).isoformat(),
                            "url": "https://social.example/@krant/1001",
                            "content": '<p>Lees <a href="https://www.krant.nl/a/1">dit</a> &amp; meer '
                            '<a href="https://social.example/tags/nieuws">#nieuws</a></p>',
                            "favourites_count": self.likes,
                            "reblogs_count": 4,
                            "replies_count": 2,
                            "account": {"id": "77"},
                        },
                        {
                            "id": "1000",
                            "created_at": (NOW - timedelta(days=2)).isoformat(),
                            "url": "https://social.example/@krant/1000",
                            "content": "<p>Antwoord</p>",
                            "favourites_count": 1,
                            "reblogs_count": 0,
                            "replies_count": 0,
                            "in_reply_to_account_id": "12",
                            "account": {"id": "77"},
                        },
                    ],
                )
        return httpx.Response(404, json={})


@pytest.fixture()
def fake(monkeypatch):
    f = Fake()
    client = httpx.Client(transport=httpx.MockTransport(f))
    monkeypatch.setattr(social, "_client", lambda c=None: c or client)
    from stats_collector import worker

    monkeypatch.setattr(worker, "social_soon", lambda source_id: None)
    return f


def test_input_cleaning():
    assert social.clean_handle("@Krant.bsky.social") == "krant.bsky.social"
    assert social.clean_handle("https://bsky.app/profile/krant.nl") == "krant.nl"
    assert social.clean_handle("nodot") == ""
    assert social.clean_account("@krant@Social.Example", "") == ("https://social.example", "krant")
    assert social.clean_account("https://social.example/@krant", "") == ("https://social.example", "krant")
    assert social.clean_account("krant", "https://mastodon.nl/") == ("https://mastodon.nl", "krant")


def _metrics(db, source_id, item_id=None):
    from sqlalchemy import select

    from stats_collector.models import MetricPoint

    rows = db.execute(
        select(MetricPoint.metric, MetricPoint.value).where(
            MetricPoint.source_id == source_id,
            MetricPoint.granularity == "day",
            MetricPoint.item_id.is_(None) if item_id is None else MetricPoint.item_id == item_id,
        )
    ).all()
    out: dict[str, float] = {}
    for m, v in rows:
        out[m] = out.get(m, 0) + v
    return out


def test_bluesky_sync(admin, fake):
    from sqlalchemy import select

    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem, Source

    client, csrf = admin
    bad = client.post("/api/sources", json={"kind": "bluesky", "name": "B", "account": "x"}, headers=csrf)
    assert bad.status_code == 422
    t = client.post(
        "/api/sources/test", json={"kind": "bluesky", "name": "B", "account": "@krant.bsky.social"}, headers=csrf
    )
    assert t.json()["ok"] and t.json()["info"]["followers"] == 500
    r = client.post(
        "/api/sources", json={"kind": "bluesky", "name": "B", "account": "@krant.bsky.social"}, headers=csrf
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert r.json()["account"] == "krant.bsky.social" and not r.json()["connected"]

    with session_factory()() as db:
        source = db.get(Source, sid)
        assert social.is_due(source, NOW)
        result = social.sync(db, source, now=NOW - timedelta(days=1))
        assert result["posts"] == 2  # the repost is skipped, the post older than a year too
        assert source.config["posts_done"] and source.config["handle"] == "@krant.bsky.social"
        items = {
            i.external_id: i for i in db.execute(select(ContentItem).where(ContentItem.source_id == sid)).scalars()
        }
        assert set(items) == {f"at://{DID}/app.bsky.feed.post/r1", f"at://{DID}/app.bsky.feed.post/r2"}
        new = items[f"at://{DID}/app.bsky.feed.post/r1"]
        assert new.url == "https://bsky.app/profile/krant.bsky.social/post/r1"
        assert new.meta["links"] == ["https://www.krant.nl/a/1?utm_source=bsky"]

        # A day later: 15 more likes and 20 more followers.
        fake.likes, fake.followers = 25, 520
        social.sync(db, source, now=NOW)
        post = _metrics(db, sid, new.id)
        assert post["bsky_likes"] == 25 and post["bsky_reposts"] == 2
        account = _metrics(db, sid)
        assert account["bsky_follows"] == 20
        assert not social.is_due(source, NOW + timedelta(minutes=10))

    data = client.get("/api/followers?range=30d").json()
    bsky = next(s for s in data["sources"] if s["kind"] == "bluesky")
    assert bsky["current"] == 520 and bsky["values"][-2:] == [500, 520]
    detail = client.get(f"/api/content/{new.id}?range=7d").json()
    assert detail["item"]["metrics"]["likes"] > 0 and detail["item"]["metrics"]["shares"] > 0


def test_mastodon_sync_needs_token(admin, fake):
    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem, Source

    client, csrf = admin
    body = {"kind": "mastodon", "name": "M", "account": "@krant@social.example"}
    t = client.post("/api/sources/test", json=body, headers=csrf).json()
    assert not t["ok"] and t["error"] == "masto_token_needed"
    r = client.post("/api/sources", json={**body, "access_token": "tok"}, headers=csrf)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["url"] == "https://social.example" and s["account"] == "krant" and s["access_token_set"]

    with session_factory()() as db:
        source = db.get(Source, s["id"])
        assert social.sync(db, source, now=NOW)["posts"] == 1  # the reply to someone else is left out
        item = db.query(ContentItem).filter_by(source_id=source.id).one()
        assert item.title == "Lees dit & meer #nieuws"
        assert item.meta["links"] == ["https://www.krant.nl/a/1"]
        assert source.config["handle"] == "@krant@social.example"
        assert _metrics(db, source.id)["masto_favourites"] == 10

    # Keeping the token: an edit without access_token leaves it in place.
    r = client.put(f"/api/sources/{s['id']}", json={**body, "name": "M2"}, headers=csrf)
    assert r.json()["access_token_set"] and r.json()["connected"]
