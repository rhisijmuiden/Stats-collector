from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from stats_collector.services import youtube

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
STARTED = date(2026, 9, 20)
METRICS = list(youtube.ANALYTICS)


class FakeGoogle:
    """Answers like the Google token endpoint, Data API v3 and Analytics API v2."""

    def __init__(self):
        self.reports = []
        self.refreshes = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.startswith(youtube.TOKEN_URL):
            body = parse_qs(req.content.decode())
            if body["grant_type"] == ["authorization_code"]:
                assert body["code_verifier"] and body["code"] == ["good-code"]
                return httpx.Response(
                    200, json={"access_token": "at-1", "refresh_token": "rt-1", "scope": youtube.SCOPES}
                )
            self.refreshes += 1
            return httpx.Response(200, json={"access_token": f"at-{self.refreshes + 1}"})
        if url.startswith(youtube.REVOKE_URL):
            self.revoked = True
            return httpx.Response(200)
        assert req.headers["Authorization"].startswith("Bearer at-")
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC123",
                            "snippet": {"title": "Krant TV", "publishedAt": f"{STARTED}T10:00:00Z"},
                            "statistics": {"subscriberCount": "1000", "videoCount": "2"},
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}},
                        }
                    ]
                },
            )
        if "/playlistItems" in url:
            return httpx.Response(
                200, json={"items": [{"contentDetails": {"videoId": "v1"}}, {"contentDetails": {"videoId": "v2"}}]}
            )
        if "/videos" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": vid,
                            "snippet": {"title": f"Video {vid}", "publishedAt": "2026-10-01T08:00:00Z", "tags": ["a"]},
                            "statistics": {"viewCount": "500", "commentCount": "4"},
                            "contentDetails": {"duration": "PT3M"},
                        }
                        for vid in q["id"].split(",")
                    ]
                },
            )
        if "youtubeanalytics" in url:
            self.reports.append(q)
            start, end = date.fromisoformat(q["startDate"]), date.fromisoformat(q["endDate"])
            assert q["metrics"].split(",") == METRICS
            if q["dimensions"] == "day":
                rows, d = [], start
                while d <= end:
                    if d >= STARTED:
                        rows.append([d.isoformat(), 100, 50, 5, 2, 1, 3, 1])
                    d += timedelta(days=1)
                return httpx.Response(200, json={"columnHeaders": [{"name": "day"}] + _h(), "rows": rows})
            assert q["dimensions"] == "video" and start == end and q["maxResults"] == "200"
            rows = [["v1", 60, 30, 3, 1, 1, 2, 0], ["gone", 10, 4, 0, 0, 0, 0, 0]]
            return httpx.Response(200, json={"columnHeaders": [{"name": "video"}] + _h(), "rows": rows})
        return httpx.Response(404)


def _h():
    return [{"name": m} for m in METRICS]


@pytest.fixture()
def google(monkeypatch):
    fake = FakeGoogle()
    client = httpx.Client(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(youtube, "_client", lambda c=None: c or client)
    from stats_collector import worker

    monkeypatch.setattr(worker, "youtube_soon", lambda source_id: None)
    return fake


def _create(client, csrf):
    r = client.post(
        "/api/sources",
        json={
            "kind": "youtube",
            "name": "YouTube",
            "client_id": "cid.apps.googleusercontent.com",
            "client_secret": "cs",
        },
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_secret_set"] and not body["connected"]
    assert body["redirect_uri"].endswith("/api/connectors/youtube/callback")
    return body


def test_connect_flow(admin, google):
    client, csrf = admin
    s = _create(client, csrf)
    r = client.get(f"/api/connectors/youtube/start?source={s['id']}", follow_redirects=False)
    assert r.status_code == 303
    loc = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    assert loc.netloc == "accounts.google.com" and q["access_type"] == "offline"
    assert q["code_challenge_method"] == "S256"
    bad = client.get("/api/connectors/youtube/callback?code=good-code&state=wrong", follow_redirects=False)
    assert "yt_error=yt_state_invalid" in bad.headers["location"]
    # The failed attempt removed the state cookie: start again.
    r = client.get(f"/api/connectors/youtube/start?source={s['id']}", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    ok = client.get(f"/api/connectors/youtube/callback?code=good-code&state={state}", follow_redirects=False)
    assert ok.status_code == 303 and "yt_connected=1" in ok.headers["location"], ok.headers["location"]
    listed = next(x for x in client.get("/api/sources").json() if x["id"] == s["id"])
    assert listed["connected"] and listed["channel_title"] == "Krant TV"
    # Saving the form again keeps the connection.
    client.put(
        f"/api/sources/{s['id']}",
        json={"kind": "youtube", "name": "YouTube", "client_id": "cid.apps.googleusercontent.com"},
        headers=csrf,
    )
    assert next(x for x in client.get("/api/sources").json() if x["id"] == s["id"])["connected"]
    out = client.post(f"/api/connectors/youtube/{s['id']}/disconnect", headers=csrf).json()
    assert out["connected"] is False and out["client_secret_set"] and google.revoked


def test_sync_imports_history_and_subscribers(admin, google):
    client, csrf = admin
    s = _create(client, csrf)
    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem, MetricPoint, Source

    with session_factory()() as db:
        source = db.get(Source, s["id"])
        youtube.connect(db, source, {"access_token": "at-1", "refresh_token": "rt-1"})
        result = youtube.sync(db, source, now=NOW)
        assert result["videos"] == 2
        assert source.config["history_done"] and source.config["subscribers"] == 1000
        day_reports = [r for r in google.reports if r["dimensions"] == "day"]
        assert [(r["startDate"], r["endDate"]) for r in day_reports] == [("2026-09-20", "2026-11-10")]
        video_days = [r["startDate"] for r in google.reports if r["dimensions"] == "video"]
        assert len(video_days) == len(set(video_days)) == (NOW.date() - STARTED).days + 1

        def points(metric, gran="day", item=None):
            q = db.query(MetricPoint).filter(
                MetricPoint.source_id == source.id, MetricPoint.metric == metric, MetricPoint.granularity == gran
            )
            q = q.filter(MetricPoint.item_id.is_(None)) if item is None else q.filter(MetricPoint.item_id == item)
            return sorted((p.bucket.replace(tzinfo=None), p.value) for p in q)

        subs = points("yt_subscribers")
        # Today 1000; each earlier day 2 fewer (3 gained, 1 lost per day).
        assert subs[-1][1] == 1000 and subs[-2][1] == 998 and subs[0][1] == 1000 - 2 * (len(subs) - 1)
        assert sum(v for _, v in points("yt_views", "month")) == 100 * len(subs)
        assert dict(points("yt_subscribers", "month"))  # last day of each month
        gone = db.query(ContentItem).filter_by(source_id=source.id, external_id="gone").one()
        assert gone.title == "gone" and gone.kind == "video"

        # Second run: only the recent days are read again.
        google.reports.clear()
        source.config = {**source.config}
        youtube.sync(db, source, now=NOW + timedelta(hours=4))
        assert len(google.reports) == 1 + youtube.RECENT_DAYS + 1

    top = client.get("/api/content/top?range=30d&source=" + str(s["id"])).json()["items"]
    v1 = next(i for i in top if i["title"] == "Video v1")
    assert v1["metrics"]["views"] == 60 * 30 and v1["metrics"]["minutes"] == 30 * 30
    assert v1["avg_watch_seconds"] == 30.0 and v1["metrics"]["likes"] == 3 * 30


def test_expired_token_is_reported(admin, monkeypatch):
    client, csrf = admin
    s = _create(client, csrf)

    def handler(req):
        return httpx.Response(400, json={"error": "invalid_grant"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    from stats_collector.connectors import ConnectorError
    from stats_collector.db import session_factory
    from stats_collector.models import Source

    with session_factory()() as db:
        source = db.get(Source, s["id"])
        source.config = {**source.config, "channel_id": "UC1"}
        import json

        from stats_collector.security import encrypt_secret

        source.secret_enc = encrypt_secret(json.dumps({"client_secret": "cs", "refresh_token": "old"}))
        db.commit()
        with pytest.raises(ConnectorError):
            youtube.sync(db, source, now=NOW, client=http)
        assert db.get(Source, s["id"]).last_error.startswith("yt_reconnect")


def test_dashboard_channels_with_demo(admin):
    client, _ = admin
    from stats_collector.db import session_factory
    from stats_collector.services.demo import create_demo

    with session_factory()() as db:
        assert create_demo(db) > 0
    data = client.get("/api/dashboard/channels?range=30d").json()
    kinds = {s["kind"]: s for s in data["sources"]}
    assert set(kinds) == {"wordpress", "youtube", "facebook", "instagram", "threads"}
    assert kinds["facebook"]["subscribers"] == 12840 and kinds["instagram"]["reach"] > 0
    assert kinds["youtube"]["views"] > 0 and kinds["youtube"]["subscribers"] == 4870
    assert kinds["wordpress"]["views"] > 0 and kinds["wordpress"]["visitors"] > 0
    assert data["total_views"] == sum(k["views"] for k in kinds.values())
    assert len(data["buckets"]) == len(kinds["youtube"]["values"])
    hourly = client.get("/api/dashboard/channels?range=24h").json()
    assert hourly["granularity"] == "hour" and len(hourly["buckets"]) == 24
