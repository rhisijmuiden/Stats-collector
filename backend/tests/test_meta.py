import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from stats_collector.services import meta

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
GONE = {"page_media_view", "post_media_view"}  # pretend Meta dropped these: the old names must be used


def _err(code, message):
    return {
        "error": {"code": code, "message": message, "type": "OAuthException" if code == 190 else "GraphMethodException"}
    }


class FakeMeta:
    """Answers like the Graph API for one Page with a linked Instagram account."""

    def __init__(self):
        self.calls = []
        self.post_views = 100

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = urlparse(str(req.url))
        path = url.path.split("/", 2)[2] if url.path.count("/") >= 2 else ""
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if req.method == "POST":
            body = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            assert body["appsecret_proof"] == meta.proof("as", body["access_token"])
            out = []
            for sub in json.loads(body["batch"]):
                u = urlparse(sub["relative_url"])
                status, data = self.answer(u.path.strip("/"), {k: v[0] for k, v in parse_qs(u.query).items()})
                out.append({"code": status, "body": json.dumps(data)})
            return httpx.Response(200, json=out)
        self.calls.append((path, q))
        if path == "oauth/access_token":
            if q.get("code"):
                assert q["code"] == "good" and q["client_secret"] == "as"
                return httpx.Response(200, json={"access_token": "short"})
            assert q["fb_exchange_token"] == "short"
            return httpx.Response(200, json={"access_token": "long-user"})
        if "appsecret_proof" in q:
            assert q["appsecret_proof"] == meta.proof("as", q["access_token"])
        status, data = self.answer(path, q)
        return httpx.Response(status, json=data)

    def answer(self, path, q):
        if path == "me/accounts":
            return 200, {
                "data": [
                    {
                        "id": "P1",
                        "name": "Krant",
                        "access_token": "page-1",
                        "link": "https://facebook.com/krant",
                        "instagram_business_account": {"id": "IG1", "username": "krant"},
                    },
                    {"id": "P2", "name": "Other page", "access_token": "page-2"},
                ]
            }
        if path in ("P1", "IG1"):
            return 200, {"name": "Krant", "username": "krant", "followers_count": 5000, "media_count": 2}
        if path.endswith("/insights"):
            names = q["metric"].split(",")
            if GONE & set(names):
                return 400, _err(100, "(#100) The value must be a valid insights metric")
            obj = path.split("/")[0]
            if obj in ("fbpost1", "fbpost2", "igpost1", "igpost2"):
                return 200, {
                    "data": [{"name": n, "period": "lifetime", "values": [{"value": self.value(n)}]} for n in names]
                }
            if obj == "IG1" and q.get("metric_type") == "total_value":
                return 200, {"data": [{"name": n, "total_value": {"value": 10}} for n in names]}
            start = datetime.fromtimestamp(int(q["since"]), UTC).date()
            end = datetime.fromtimestamp(int(q["until"]), UTC).date()
            series = []
            for n in names:
                values, d = [], start
                while d < end:
                    ending = datetime.combine(d + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=8)
                    values.append(
                        {
                            "value": 3 if "unfollow" in n else 7 if "follow" in n else 50,
                            "end_time": ending.strftime("%Y-%m-%dT%H:%M:%S+0000"),
                        }
                    )
                    d += timedelta(days=1)
                series.append({"name": n, "period": "day", "values": values})
            return 200, {"data": series}
        if path == "P1/posts":
            posts = [
                {
                    "id": "fbpost1",
                    "message": "Nieuw artikel over de haven",
                    "created_time": "2026-11-09T09:00:00+0000",
                    "permalink_url": "https://facebook.com/p/1",
                    "shares": {"count": 4},
                    "comments": {"summary": {"total_count": 2}},
                    "reactions": {"summary": {"total_count": 30}},
                },
                {
                    "id": "fbpost2",
                    "message": "Oud bericht",
                    "created_time": "2026-10-01T09:00:00+0000",
                    "permalink_url": "https://facebook.com/p/2",
                    "reactions": {"summary": {"total_count": 5}},
                },
            ]
            if "since" in q:
                since = int(q["since"])
                posts = [p for p in posts if datetime.fromisoformat(p["created_time"]).timestamp() >= since]
            return 200, {"data": posts}
        if path == "IG1/media":
            return 200, {
                "data": [
                    {
                        "id": "igpost1",
                        "caption": "Reel van de markt",
                        "media_product_type": "REELS",
                        "permalink": "https://instagram.com/p/1",
                        "timestamp": "2026-11-08T10:00:00+0000",
                        "like_count": 80,
                        "comments_count": 6,
                    },
                ]
            }
        if path.endswith("/insights") is False and "/" not in path:
            return 404, _err(803, "unknown object")
        return 404, _err(100, "unknown path")

    def value(self, name):
        if name == "post_reactions_by_type_total":
            return {"like": 20, "love": 10}
        if name in ("post_impressions", "views"):
            return self.post_views
        return 10


@pytest.fixture()
def graph(monkeypatch):
    fake = FakeMeta()
    client = httpx.Client(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(meta, "_client", lambda c=None: c or client)
    from stats_collector import worker

    monkeypatch.setattr(worker, "meta_soon", lambda source_id: None)
    return fake


def _create(client, csrf, kind):
    r = client.post(
        "/api/sources",
        json={"kind": kind, "name": kind.title(), "client_id": "123", "client_secret": "as"},
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_secret_set"] and not body["connected"]
    assert body["redirect_uri"].endswith("/api/connectors/meta/callback")
    return body


def test_connect_with_choice(admin, graph):
    client, csrf = admin
    s = _create(client, csrf, "facebook")
    r = client.get(f"/api/connectors/meta/start?source={s['id']}", follow_redirects=False)
    loc = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    assert loc.netloc == "www.facebook.com" and "read_insights" in q["scope"]
    done = client.get(f"/api/connectors/meta/callback?code=good&state={q['state']}", follow_redirects=False)
    assert "meta_choose=1" in done.headers["location"]  # two Pages: the admin picks one
    listed = next(x for x in client.get("/api/sources").json() if x["id"] == s["id"])
    assert [c["name"] for c in listed["choices"]] == ["Krant", "Other page"] and not listed["connected"]
    out = client.post(f"/api/connectors/meta/{s['id']}/choose", json={"account_id": "P1"}, headers=csrf).json()
    assert out["connected"] and out["account_name"] == "Krant" and out["choices"] == []
    out = client.post(f"/api/connectors/meta/{s['id']}/disconnect", headers=csrf).json()
    assert not out["connected"] and out["client_secret_set"]

    # Instagram: only one Page has an account, so it is picked straight away.
    ig = _create(client, csrf, "instagram")
    r = client.get(f"/api/connectors/meta/start?source={ig['id']}", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    done = client.get(f"/api/connectors/meta/callback?code=good&state={state}", follow_redirects=False)
    assert "meta_connected=1" in done.headers["location"], done.headers["location"]
    listed = next(x for x in client.get("/api/sources").json() if x["id"] == ig["id"])
    assert listed["connected"] and listed["account_name"] == "@krant"


def _connected(kind, account):
    from stats_collector.db import session_factory
    from stats_collector.models import Source
    from stats_collector.security import encrypt_secret

    with session_factory()() as db:
        s = Source(kind=kind, name=kind, config={"client_id": "123", "account_id": account, "account_name": account})
        s.secret_enc = encrypt_secret(json.dumps({"client_secret": "as", "page_token": "page-1"}))
        db.add(s)
        db.commit()
        return s.id


def _points(db, source_id, metric, gran="day", item=False):
    from stats_collector.models import MetricPoint

    q = db.query(MetricPoint).filter(
        MetricPoint.source_id == source_id, MetricPoint.metric == metric, MetricPoint.granularity == gran
    )
    q = q.filter(MetricPoint.item_id.is_not(None) if item else MetricPoint.item_id.is_(None))
    return sorted((p.bucket.replace(tzinfo=None), p.value) for p in q)


def test_facebook_sync(admin, graph):
    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem, Source

    sid = _connected("facebook", "P1")
    with session_factory()() as db:
        source = db.get(Source, sid)
        meta.sync(db, source, now=NOW)
        cfg = source.config
        assert cfg["history_done"] and cfg["followers"] == 5000
        # The new names were refused, the older ones work and are remembered for this version.
        assert cfg["metric_names"]["page"]["fb_views"] == "page_impressions"
        assert cfg["metric_names"]["post"]["fb_views"] == "post_impressions"
        views = _points(db, sid, "fb_views")
        assert len(views) == meta.FB_HISTORY_DAYS and {v for _, v in views} == {50}
        followers = _points(db, sid, "fb_followers")
        assert followers[-1][1] == 5000 and followers[-2][1] == 5000 - 4  # 7 followed, 3 left per day
        # Posts: their whole total on the day they came out, the reactions also in the page total.
        post = db.query(ContentItem).filter_by(source_id=sid, external_id="fbpost1").one()
        assert post.title == "Nieuw artikel over de haven" and post.meta["reactions"] == {"like": 20, "love": 10}
        assert _points(db, sid, "fb_reactions", item=True) == [
            (datetime(2026, 9, 30, 22, 0), 5.0),
            (datetime(2026, 11, 8, 23, 0), 30.0),
        ]
        assert sum(v for _, v in _points(db, sid, "fb_reactions")) == 35
        assert _points(db, sid, "fb_views", "month")

        # Next hour the post gained 40 views: that lands on today.
        graph.post_views = 140
        graph.calls.clear()
        meta.sync(db, source, now=NOW + timedelta(hours=1))
        today = [v for b, v in _points(db, sid, "fb_views", item=True) if b == datetime(2026, 11, 9, 23, 0)]
        assert today == [40.0]
        page_calls = [c for c in graph.calls if c[0] == "P1/insights"]
        assert len(page_calls) == 1  # history is in: only the last days again

    top = client_top(admin, sid)
    assert top["metrics"]["likes"] == 30 and top["metrics"]["views"] == 140


def client_top(admin, sid):
    client, _ = admin
    items = client.get(f"/api/content/top?range=30d&source={sid}").json()["items"]
    return next(i for i in items if i["title"].startswith("Nieuw artikel"))


def test_instagram_sync(admin, graph):
    from stats_collector.db import session_factory
    from stats_collector.models import Source

    sid = _connected("instagram", "IG1")
    with session_factory()() as db:
        source = db.get(Source, sid)
        meta.sync(db, source, now=NOW)
        cfg = source.config
        assert not cfg["history_done"] and cfg["days_until"]  # 90 days come in slices of 30
        assert len(_points(db, sid, "ig_reach")) == meta.RECENT_DAYS + 1 + meta.IG_DAYS_PER_RUN
        assert _points(db, sid, "ig_likes", item=True)[0][1] == 80
        for hour in range(1, 4):
            meta.sync(db, source, now=NOW + timedelta(hours=hour))
        assert source.config["history_done"]
        assert len(_points(db, sid, "ig_reach")) == meta.IG_HISTORY_DAYS
        assert _points(db, sid, "ig_followers")[-1][1] == 5000


def test_expired_token(admin, monkeypatch):
    from stats_collector.connectors import ConnectorError
    from stats_collector.db import session_factory
    from stats_collector.models import Source

    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json=_err(190, "expired"))))
    sid = _connected("facebook", "P1")
    with session_factory()() as db:
        with pytest.raises(ConnectorError):
            meta.sync(db, db.get(Source, sid), now=NOW, client=http)
        assert db.get(Source, sid).last_error.startswith("meta_reconnect")


def test_overrides_are_validated(admin):
    client, csrf = admin
    r = client.post(
        "/api/sources",
        json={
            "kind": "facebook",
            "name": "FB",
            "client_id": "123",
            "graph_version": "v24.0",
            "metric_overrides": {"fb_views": "page_views_new", "nope": "x", "fb_reach": "bad name;"},
        },
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    assert r.json()["metric_overrides"] == {"fb_views": "page_views_new"} and r.json()["graph_version"] == "v24.0"
    assert (
        client.post(
            "/api/sources",
            json={"kind": "facebook", "name": "x", "client_id": "1", "graph_version": "latest"},
            headers=csrf,
        ).status_code
        == 422
    )
