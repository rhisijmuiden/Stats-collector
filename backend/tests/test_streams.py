from datetime import UTC, datetime, timedelta

import httpx
import pytest

from stats_collector.connectors import ConnectorError, Observation, PollResult, icecast, owncast

ICE_STATUS = {
    "icestats": {
        "server_id": "Icecast 2.4.4",
        "source": [
            {"listenurl": "http://radio.local:8000/live", "listeners": 12, "server_name": "Live", "title": "Song A"},
            {"listenurl": "http://radio.local:8000/jazz", "listeners": 3, "server_name": "Jazz"},
        ],
    }
}
LISTCLIENTS = """<?xml version="1.0"?><icestats><source mount="/live"><Listeners>2</Listeners>
<listener id="1"><IP>192.0.2.1</IP><UserAgent>VLC/3.0</UserAgent><Connected>100</Connected></listener>
<listener id="2"><IP>192.0.2.2</IP><UserAgent>Mozilla/5.0 Chrome/120</UserAgent><Connected>300</Connected></listener>
</source></icestats>"""


def mock_client(monkeypatch, module, handler):
    monkeypatch.setattr(module, "http_client", lambda cfg: httpx.Client(transport=httpx.MockTransport(handler)))


def test_icecast_poll(monkeypatch):
    def handler(req: httpx.Request):
        if req.url.path == "/status-json.xsl":
            return httpx.Response(200, json=ICE_STATUS)
        if req.url.path == "/admin/listclients":
            assert req.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, text=LISTCLIENTS)
        return httpx.Response(404)

    mock_client(monkeypatch, icecast, handler)
    res = icecast.IcecastConnector().poll(
        {"url": "http://radio.local:8000", "mounts": ["live", "/missing"]}, {"admin_password": "x"}
    )
    by_id = {o.external_id: o for o in res.observations}
    assert set(by_id) == {"/live", "/missing"}
    assert by_id["/live"].value == 12 and by_id["/live"].extra["avg_connected_s"] == 200
    assert by_id["/live"].extra["agents"] == {"VLC": 1, "Chrome": 1}
    assert "192.0.2.1" not in str(by_id["/live"].extra)
    assert by_id["/missing"].online is False and res.online is True
    # all mounts when none are configured; a single source comes back as a dict
    one = {"icestats": {"source": ICE_STATUS["icestats"]["source"][1]}}
    mock_client(monkeypatch, icecast, lambda r: httpx.Response(200, json=one))
    res = icecast.IcecastConnector().poll({"url": "http://radio.local:8000"}, {})
    assert [o.external_id for o in res.observations] == ["/jazz"]


def test_icecast_errors(monkeypatch):
    mock_client(monkeypatch, icecast, lambda r: httpx.Response(404))
    with pytest.raises(ConnectorError, match="not_found"):
        icecast.IcecastConnector().poll({"url": "http://radio.local:8000"}, {})
    with pytest.raises(ConnectorError, match="invalid_url"):
        icecast.IcecastConnector().poll({"url": "radio.local"}, {})


def test_owncast_poll(monkeypatch):
    state = {"online": True}

    def handler(req: httpx.Request):
        if req.url.path == "/api/status":
            if state["online"]:
                return httpx.Response(200, json={"online": True, "viewerCount": 7, "streamTitle": "Ochtendshow",
                                                 "lastConnectTime": "2026-11-10T07:00:00Z", "versionNumber": "0.2.0"})
            return httpx.Response(200, json={"online": False, "viewerCount": 0, "lastConnectTime": None})
        if req.url.path == "/api/config":
            return httpx.Response(200, json={"name": "TV"})
        return httpx.Response(404)

    mock_client(monkeypatch, owncast, handler)
    res = owncast.OwncastConnector().poll({"url": "https://tv.local"}, {})
    assert res.online and res.observations[0].external_id == "broadcast:2026-11-10T07:00:00Z"
    assert res.observations[0].title == "Ochtendshow" and res.observations[0].value == 7
    state["online"] = False
    res = owncast.OwncastConnector().poll({"url": "https://tv.local"}, {})
    assert not res.online and res.observations == []


class FakeConnector:
    kind = "icecast"
    stream = True

    def __init__(self):
        self.values = {"/live": 10.0, "/jazz": 2.0}

    def poll(self, config, secrets):
        return PollResult(online=True, observations=[
            Observation(external_id=k, kind="mount", title=k, value=v) for k, v in self.values.items()
        ])


def test_collect_and_rollup(app_env, monkeypatch):
    from sqlalchemy import select

    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem, MetricPoint, Source, StreamSample
    from stats_collector.services import collect, rollup

    fake = FakeConnector()
    monkeypatch.setattr(collect, "get_connector", lambda kind: fake)
    t0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    with session_factory()() as db:
        src = Source(kind="icecast", name="Radio", config={"url": "http://x"}, poll_seconds=30)
        db.add(src)
        db.commit()
        for i in range(120):  # one hour every 30 s
            collect.poll_source(db, src, now=t0 + timedelta(seconds=30 * i))
        assert db.query(StreamSample).count() == 240
        assert db.query(ContentItem).count() == 2
        assert [s.id for s in collect.due_sources(db, now=t0 + timedelta(seconds=30 * 119 + 10))] == []
        assert [s.id for s in collect.due_sources(db, now=t0 + timedelta(seconds=30 * 120))] == [src.id]

        rollup.rollup(db, since=t0, now=t0 + timedelta(minutes=59))
        pts = {(p.item_id, p.granularity, p.metric): p.value for p in db.execute(select(MetricPoint)).scalars()}
        assert pts[(None, "hour", "live_minutes")] == pytest.approx(720)  # 12 listeners x 60 min
        assert pts[(None, "hour", "live_avg")] == pytest.approx(12)
        assert pts[(None, "hour", "live_peak")] == 12
        assert pts[(None, "day", "live_minutes")] == pytest.approx(720)
        assert pts[(None, "month", "live_minutes")] == pytest.approx(720)
        live = db.execute(select(ContentItem).where(ContentItem.external_id == "/live")).scalar_one()
        assert pts[(live.id, "hour", "live_minutes")] == pytest.approx(600)
        # running the rollup again replaces, it does not add up
        rollup.rollup(db, since=t0, now=t0 + timedelta(minutes=59))
        assert db.query(MetricPoint).filter_by(item_id=None, granularity="hour", metric="live_minutes").count() == 1


def test_gap_is_not_filled():
    from stats_collector.services.rollup import summarise

    t0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    pts = [(t0, 10.0), (t0 + timedelta(minutes=30), 10.0)]  # collector down for 30 minutes
    out = summarise(pts, t0, t0 + timedelta(hours=1), 30)
    assert out["live_minutes"] == pytest.approx(10.0)  # two samples, 30 s each


def test_offline_broadcast_ends(app_env, monkeypatch):
    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem, Source
    from stats_collector.services import collect

    class Own:
        online = True

        def poll(self, config, secrets):
            if self.online:
                obs = Observation("broadcast:1", "broadcast", "Show", 5, started_at="2026-11-10T08:00:00Z")
                return PollResult(True, [obs])
            return PollResult(False, [])

    own = Own()
    monkeypatch.setattr(collect, "get_connector", lambda kind: own)
    with session_factory()() as db:
        src = Source(kind="owncast", name="TV", config={"url": "http://x"})
        db.add(src)
        db.commit()
        collect.poll_source(db, src)
        own.online = False
        collect.poll_source(db, src)
        item = db.query(ContentItem).one()
        assert item.ended_at is not None and item.published_at.hour == 8


def test_poll_error_is_recorded(app_env, monkeypatch):
    from stats_collector.db import session_factory
    from stats_collector.models import Source
    from stats_collector.services import collect

    class Broken:
        def poll(self, config, secrets):
            raise ConnectorError("unauthorized")

    monkeypatch.setattr(collect, "get_connector", lambda kind: Broken())
    with session_factory()() as db:
        src = Source(kind="icecast", name="R", config={"url": "http://x"})
        db.add(src)
        db.commit()
        assert collect.poll_source(db, src) is None
        assert src.last_error == "unauthorized" and src.last_poll_at is not None


def test_sources_api_and_dashboard(admin, monkeypatch):
    from stats_collector.services import collect

    client, csrf = admin
    fake = FakeConnector()
    monkeypatch.setattr(collect, "get_connector", lambda kind: fake)
    body = {"kind": "icecast", "name": "Radio", "url": "http://radio.local:8000/", "mounts": ["live"],
            "admin_password": "secret"}
    r = client.post("/api/sources", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    src = r.json()
    assert src["url"] == "http://radio.local:8000" and src["mounts"] == ["/live"] and src["admin_password_set"]
    assert "secret" not in r.text
    t = client.post("/api/sources/test", json={**body, "id": src["id"], "admin_password": None}, headers=csrf)
    assert t.json()["ok"] and len(t.json()["items"]) == 2
    # keep the password when it is not sent again
    r = client.put(f"/api/sources/{src['id']}", json={**body, "admin_password": None, "name": "Radio 1"}, headers=csrf)
    assert r.json()["admin_password_set"] and r.json()["name"] == "Radio 1"
    assert client.post(f"/api/sources/{src['id']}/poll", headers=csrf).json()["last_ok_at"]
    live = client.get("/api/dashboard/live").json()
    assert live["total"] == 12 and live["sources"][0]["online"]
    series = client.get("/api/dashboard/series?range=24h").json()
    assert len(series["buckets"]) == 288 and any(v == 12 for v in series["series"][0]["values"])
    for rng in ("7d", "30d"):
        assert client.get(f"/api/dashboard/series?range={rng}&metric=live_minutes").status_code == 200
    assert client.get("/api/dashboard/summary?range=7d").status_code == 200
    assert client.delete(f"/api/sources/{src['id']}", headers=csrf).json()["ok"]


def test_owncast_webhook(admin, monkeypatch):
    from stats_collector import worker

    client, csrf = admin
    polled = []
    monkeypatch.setattr(worker, "poll_soon", lambda sid: polled.append(sid))
    r = client.post("/api/sources", json={"kind": "owncast", "name": "TV", "url": "https://tv.local"}, headers=csrf)
    hook = r.json()["webhook_url"]
    assert hook and "/api/hooks/owncast/" in hook
    path = "/api/hooks/owncast/" + hook.rsplit("/", 1)[1]
    assert client.post(path, json={"type": "STREAM_STARTED"}).json()["ok"]
    assert polled == [r.json()["id"]]
    assert client.post("/api/hooks/owncast/wrong-token-wrong-token", json={}).status_code == 404
    old = path
    client.post(f"/api/sources/{r.json()['id']}/rotate-webhook", headers=csrf)
    assert client.post(old, json={}).status_code == 404


def test_staff_cannot_manage_sources(admin):
    client, csrf = admin
    client.post("/api/users", json={"email": "s@example.org", "display_name": "S", "role": "staff",
                                    "password": "correct horse battery"}, headers=csrf)
    client.post("/api/auth/logout", headers=csrf)
    r = client.post("/api/auth/login", json={"email": "s@example.org", "password": "correct horse battery"})
    assert r.status_code == 200
    assert client.get("/api/sources").status_code == 403
    assert client.get("/api/dashboard/live").status_code == 200
