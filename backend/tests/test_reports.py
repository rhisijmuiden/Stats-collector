from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

PW = "correct horse battery"
AMS = ZoneInfo("Europe/Amsterdam")


def _demo():
    from stats_collector.db import session_factory
    from stats_collector.services.demo import create_demo

    with session_factory()() as db:
        assert create_demo(db) > 0


def test_periods_and_schedule():
    from stats_collector.models import Report
    from stats_collector.services.reports import next_run, windows

    now = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)  # a Tuesday
    (start, end, gran, buckets), (p_start, p_end, _, p_buckets) = windows("last_month", now, AMS)
    assert start == datetime(2026, 9, 30, 22, tzinfo=UTC) and end == datetime(2026, 10, 31, 23, tzinfo=UTC)
    assert gran == "day" and len(buckets) == 31 and len(p_buckets) == 30 and p_end == start
    (start, end, _, buckets), _ = windows("last_week", now, AMS)
    assert start.astimezone(AMS).date().isoformat() == "2026-11-02" and len(buckets) == 7
    (start, end, _, buckets), _ = windows("yesterday", now, AMS)
    assert start.astimezone(AMS).date().isoformat() == "2026-11-09" and len(buckets) == 1

    r = Report(schedule="monthly", monthday=1, send_time="08:00", weekday=0, enabled=True)
    assert next_run(r, now, AMS) == datetime(2026, 12, 1, 7, tzinfo=UTC)
    r.schedule = "weekly"
    assert next_run(r, now, AMS) == datetime(2026, 11, 16, 7, tzinfo=UTC)
    r.schedule = "daily"
    assert next_run(r, now, AMS) == datetime(2026, 11, 11, 7, tzinfo=UTC)
    r.enabled = False
    assert next_run(r, now, AMS) is None


@pytest.fixture()
def sent(monkeypatch):
    """Collects mail instead of sending it, and stands in for Chromium."""
    from stats_collector.services import mail
    from stats_collector.services import reports as svc

    out = []
    monkeypatch.setattr(mail, "send", lambda cfg, m: out.append(m))
    monkeypatch.setattr(mail, "configured", lambda cfg: True)

    def fake_pdf(run, token):
        path = svc.pdf_file(run)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.7 test")
        return b"%PDF-1.7 test"

    monkeypatch.setattr(svc, "render_pdf", fake_pdf)
    return out


BLOCKS = [
    {"id": "k1", "type": "kpi", "measure": "reach", "size": "small"},
    {"id": "c1", "type": "chart", "measure": "views", "split": "platform", "size": "full"},
    {"id": "t1", "type": "top", "sort": "views", "limit": 5},
    {"id": "g1", "type": "goals"},
    {"id": "x1", "type": "text", "title": "Notes", "text": "Hello"},
]


def test_report_generate_send_and_link(admin, sent):
    client, csrf = admin
    _demo()
    body = {"name": "Monthly", "blocks": BLOCKS, "period": "last_30d", "recipient_emails": ["Board@Example.org"]}
    r = client.post("/api/reports", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["recipient_emails"] == ["board@example.org"] and rep["can_send"] and rep["next_run_at"] is None

    run = client.post(f"/api/reports/{rep['id']}/generate", headers=csrf).json()
    token = run["link"].rsplit("/", 1)[1]
    public = client.get(f"/api/public/reports/{token}").json()
    kinds = [b["block"]["type"] for b in public["blocks"]]
    assert kinds == ["kpi", "chart", "top", "goals", "text"]
    assert public["blocks"][0]["data"]["total"] > 0 and public["blocks"][2]["data"]["items"]
    assert len(public["blocks"][1]["data"]["buckets"]) == 30
    assert client.get("/api/public/reports/not-a-real-token-at-all-xx").status_code == 404

    out = client.post(f"/api/reports/{rep['id']}/send", headers=csrf).json()
    assert out["status"] == "sent" and out["recipients"] == ["board@example.org"]
    m = sent[-1]
    assert m.to == ["board@example.org"] and m.attachments[0][1] == "application/pdf"
    assert "/r/" in m.text and "Monthly" in m.subject
    runs = client.get(f"/api/reports/{rep['id']}/runs").json()
    assert [x["status"] for x in runs] == ["sent", "generated"]
    assert client.get(f"/api/reports/runs/{out['id']}/pdf").content.startswith(b"%PDF")

    # Expired links stop working; the archive keeps the run.
    from stats_collector.db import session_factory
    from stats_collector.models import ReportRun

    with session_factory()() as db:
        x = db.get(ReportRun, run["id"])
        x.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    assert client.get(f"/api/public/reports/{token}").status_code == 410
    assert client.get(f"/api/reports/runs/{run['id']}").status_code == 200


def test_editors_block_rules_and_schedule(admin, sent):
    client, csrf = admin
    _demo()
    blocks = [*BLOCKS, {"id": "e1", "type": "editors"}]
    bad = {"name": "Editors", "blocks": blocks, "recipient_emails": ["x@example.org"]}
    assert client.post("/api/reports", json=bad, headers=csrf).json()["detail"] == "editors_recipients"
    me = client.get("/api/auth/me").json()["user"]
    body = {
        "name": "Editors",
        "blocks": blocks,
        "recipient_users": [me["id"]],
        "schedule": "weekly",
        "weekday": 0,
        "send_time": "7:30",
        "period": "last_week",
    }
    rep = client.post("/api/reports", json=body, headers=csrf).json()
    assert rep["send_time"] == "07:30" and rep["next_run_at"]

    from stats_collector.db import session_factory
    from stats_collector.models import Report
    from stats_collector.services.reports import run_due

    with session_factory()() as db:
        report = db.get(Report, rep["id"])
        due = report.next_run_at.replace(tzinfo=UTC)  # SQLite gives naive times
        assert run_due(db, now=due - timedelta(minutes=1)) == 0
        assert run_due(db, now=due + timedelta(minutes=1)) == 1
        assert db.get(Report, rep["id"]).next_run_at.replace(tzinfo=UTC) > due
    assert sent[-1].to == ["admin@example.org"]
    data = client.get(f"/api/reports/runs/{client.get(f'/api/reports/{rep["id"]}/runs').json()[0]['id']}").json()
    assert data["blocks"][-1]["data"]["editors"]

    # An editor makes their own reports, without the ranking, a schedule or recipients.
    client.post(
        "/api/users",
        json={"email": "ed@example.org", "display_name": "Ed", "role": "editor", "password": PW},
        headers=csrf,
    )
    client.post("/api/auth/logout", headers=csrf)
    client.cookies.clear()
    login = client.post("/api/auth/login", json={"email": "ed@example.org", "password": PW})
    ed = {"X-CSRF-Token": login.json()["csrf_token"]}
    assert client.post("/api/reports", json={"name": "Mine", "blocks": blocks}, headers=ed).status_code == 403
    mine = client.post("/api/reports", json={"name": "Mine", "blocks": BLOCKS}, headers=ed).json()
    assert [r["name"] for r in client.get("/api/reports").json()] == ["Mine"]
    assert client.post(f"/api/reports/{mine['id']}/generate", headers=ed).status_code == 200
    assert client.post(f"/api/reports/{mine['id']}/send", headers=ed).status_code == 403
    assert client.get(f"/api/reports/{rep['id']}/runs").status_code == 404


def test_graph_mail(monkeypatch):
    import httpx

    from stats_collector.security import encrypt_secret
    from stats_collector.services import mail

    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        if url.endswith("/token"):
            assert kw["data"]["scope"] == "https://graph.microsoft.com/.default"
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(202)

    monkeypatch.setenv("SC_SECRET_KEY", "test-secret")
    monkeypatch.setattr(mail.httpx, "post", fake_post)
    cfg = {
        "transport": "graph",
        "graph_tenant_id": "t1",
        "graph_client_id": "c1",
        "graph_client_secret_enc": encrypt_secret("s"),
        "graph_mailbox": "reports@example.org",
        "from_name": "Stats",
    }
    m = mail.OutgoingMail(
        to=["a@example.org"],
        subject="S",
        text="T",
        html="<p>T</p>",
        attachments=[("r.pdf", "application/pdf", b"%PDF")],
    )
    mail.send(cfg, m)
    url, kw = calls[-1]
    assert url == "https://graph.microsoft.com/v1.0/users/reports@example.org/sendMail"
    msg = kw["json"]["message"]
    assert msg["toRecipients"][0]["emailAddress"]["address"] == "a@example.org"
    assert msg["attachments"][0]["name"] == "r.pdf" and kw["headers"]["Authorization"] == "Bearer tok"

    # Graph refuses: with an SMTP server set up, that is used instead.
    used = []
    monkeypatch.setattr(mail, "send_graph", lambda c, x: (_ for _ in ()).throw(mail.MailError("graph_send_failed")))
    monkeypatch.setattr(mail, "send_smtp", lambda c, x: used.append(x))
    mail.send({**cfg, "host": "smtp.example.org"}, m)
    assert used == [m]
    with pytest.raises(mail.MailError):
        mail.send(cfg, m)
    assert mail.build_message({"from_address": "a@example.org"}, m).get_payload()[-1].get_filename() == "r.pdf"
