from stats_collector.services import mail


def test_email_secret_hidden_and_kept(admin):
    client, csrf = admin
    body = {
        "enabled": True,
        "host": "smtp.example.org",
        "port": 587,
        "username": "u",
        "password": "pw",
        "from_address": "stats@example.org",
    }
    r = client.put("/api/settings/email", json=body, headers=csrf).json()
    assert r["password_set"] is True and "password_enc" not in r and "password" not in r
    body.pop("password")
    r = client.put("/api/settings/email", json=body, headers=csrf).json()
    assert r["password_set"] is True  # omitted password keeps the stored one
    r = client.put("/api/settings/email", json={**body, "password": ""}, headers=csrf).json()
    assert r["password_set"] is False


def test_email_test_sends(admin, monkeypatch):
    client, csrf = admin
    sent = {}

    def fake_send(cfg, m):
        sent["cfg"], sent["mail"] = cfg, m

    monkeypatch.setattr(mail, "send", fake_send)
    client.put("/api/settings/email", json={"host": "smtp.example.org", "from_address": "s@example.org"}, headers=csrf)
    r = client.post("/api/settings/email/test", json={"to": "me@example.org"}, headers=csrf)
    assert r.status_code == 200
    assert sent["mail"].subject == "Testmail van Stats Collector"  # admin language is nl


def test_email_test_reports_error(admin, monkeypatch):
    client, csrf = admin

    def boom(cfg, m):
        raise mail.MailError("SMTPAuthenticationError: 535")

    monkeypatch.setattr(mail, "send", boom)
    r = client.post("/api/settings/email/test", json={"to": "me@example.org"}, headers=csrf)
    assert r.status_code == 502 and "535" in r.json()["detail"]


def test_build_message_headers():
    msg = mail.build_message(
        {"from_address": "stats@example.org", "from_name": "Stats", "reply_to": "r@example.org"},
        mail.OutgoingMail(to=["a@example.org"], subject="Hi", text="t", html="<p>t</p>"),
    )
    assert msg["From"] == "Stats <stats@example.org>"
    assert msg["Message-ID"].endswith("@example.org>")
    assert msg.is_multipart()


def test_tls_context_minimum():
    import ssl

    assert mail.tls_context().minimum_version == ssl.TLSVersion.TLSv1_2


def test_branding(admin):
    client, csrf = admin
    theme = client.get("/api/branding").json()
    assert theme["colors"]["light"]["accent"] == "#0E9F8E"
    r = client.put(
        "/api/settings/branding",
        json={"app_name": "IJmond Stats", "overrides": {"colors": {"light": {"accent": "#123456"}}}},
        headers=csrf,
    )
    assert r.json()["colors"]["light"]["accent"] == "#123456"
    assert r.json()["colors"]["light"]["surface"] == "#FFFFFF"
    assert r.json()["app_name"] == "IJmond Stats"
    bad = client.put(
        "/api/settings/branding", json={"overrides": {"colors": {"light": {"accent": "red;"}}}}, headers=csrf
    )
    assert bad.status_code == 400
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    up = client.post("/api/settings/branding/logo_light", files={"file": ("l.svg", svg, "image/svg+xml")}, headers=csrf)
    assert up.json()["detail"] == "unsafe_svg"
    ok = client.post(
        "/api/settings/branding/logo_light",
        files={"file": ("l.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")},
        headers=csrf,
    )
    assert ok.json()["assets"]["logo_light"] == "/api/branding/asset/logo_light"
    assert client.get("/api/branding/asset/logo_light").status_code == 200


def test_sso_settings(admin):
    client, csrf = admin
    r = client.put(
        "/api/settings/sso",
        json={
            "enabled": True,
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "group_roles": {"admin": " g1 ", "hacker": "x"},
        },
        headers=csrf,
    ).json()
    assert r["client_secret_set"] is True and r["group_roles"]["admin"] == "g1" and "hacker" not in r["group_roles"]
    assert client.get("/api/settings/sso").json()["redirect_uri"].endswith("/api/auth/entra/callback")


def test_help(client):
    idx = client.get("/api/help?lang=nl").json()
    assert idx["lang"] == "nl" and any(p["slug"] == "README" or p["slug"] for p in idx["pages"])
    first = idx["pages"][0]["slug"]
    page = client.get(f"/api/help/{first}?lang=nl").json()
    assert page["markdown"].startswith("#")
    assert client.get("/api/help/..%2Fsecret").status_code == 404
