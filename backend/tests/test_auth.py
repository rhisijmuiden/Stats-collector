from conftest import make_token


def test_status_needs_setup(client):
    r = client.get("/api/auth/status")
    assert r.json()["needs_setup"] is True


def test_setup_rejects_bad_token(client):
    r = client.post(
        "/api/auth/setup",
        json={"token": "nope", "email": "a@example.org", "display_name": "A", "password": "x" * 12},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "setup_token_invalid"


def test_setup_token_single_use(admin):
    client, _ = admin
    r = client.post(
        "/api/auth/setup",
        json={"token": make_token(), "email": "b@example.org", "display_name": "B", "password": "y" * 12},
    )
    assert r.json()["detail"] == "setup_already_done"


def test_login_me_logout_and_csrf(admin):
    client, csrf = admin
    me = client.get("/api/auth/me").json()
    assert me["user"]["role"] == "admin" and me["user"]["language"] == "nl"
    # mutating without CSRF header is refused
    assert client.patch("/api/auth/me", json={"theme": "dark"}).status_code == 403
    assert client.patch("/api/auth/me", json={"theme": "dark"}, headers=csrf).json()["theme"] == "dark"
    assert client.post("/api/auth/logout", headers=csrf).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", json={"email": "admin@example.org", "password": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"email": "ADMIN@example.org", "password": "correct horse battery"})
    assert ok.status_code == 200


def test_login_rate_limited(client):
    codes = [
        client.post("/api/auth/login", json={"email": "x@example.org", "password": "nope"}).status_code
        for _ in range(12)
    ]
    assert codes[-1] == 429


def test_totp_flow(admin):
    import pyotp

    client, csrf = admin
    setup = client.get("/api/auth/totp/setup").json()
    code = pyotp.TOTP(setup["secret"]).now()
    r = client.post("/api/auth/totp/enable", json={"secret": setup["secret"], "code": code}, headers=csrf)
    assert r.json()["totp_enabled"] is True
    client.post("/api/auth/logout", headers=csrf)
    creds = {"email": "admin@example.org", "password": "correct horse battery"}
    assert client.post("/api/auth/login", json=creds).json()["detail"] == "totp_required"
    r = client.post("/api/auth/login", json={**creds, "totp": pyotp.TOTP(setup["secret"]).now()})
    assert r.status_code == 200
