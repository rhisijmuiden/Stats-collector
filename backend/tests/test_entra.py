import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from stats_collector.services import entra

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def fake_entra(monkeypatch):
    doc = {
        "issuer": ISSUER,
        "authorization_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize",
        "token_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
        "jwks_uri": f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys",
    }
    monkeypatch.setattr(entra, "discovery", lambda tenant: doc)
    monkeypatch.setattr(entra, "_signing_key", lambda uri, token: KEY.public_key())
    claims = {"groups": ["g-admins"], "name": "Reinder", "email": "reinder@example.org", "oid": "o-1"}
    seen = {}

    def exchange(cfg, secret, code, verifier, redirect_uri):
        assert secret == "s3cret" and code == "the-code" and verifier
        now = int(time.time())
        token = jwt.encode({"iss": ISSUER, "aud": CLIENT, "sub": "sub-1", "tid": TENANT, "iat": now,
                            "exp": now + 600, "nonce": seen["nonce"], **claims}, KEY, algorithm="RS256")
        return {"id_token": token, "access_token": "at"}

    monkeypatch.setattr(entra, "exchange_code", exchange)
    return claims, seen


def configure(client, csrf, **over):
    body = {"enabled": True, "tenant_id": TENANT, "client_id": CLIENT, "client_secret": "s3cret",
            "allow_local_login": True, "default_role": "staff",
            "group_roles": {"admin": "g-admins", "editor_in_chief": "", "editor": "g-editors", "staff": ""}}
    body.update(over)
    r = client.put("/api/settings/sso", json=body, headers=csrf)
    assert r.status_code == 200, r.text


def sign_in(client, seen, code="the-code"):
    r = client.get("/api/auth/entra/start?next=/dashboard", follow_redirects=False)
    assert r.status_code == 303, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == [CLIENT]
    seen["nonce"] = q["nonce"][0]
    return client.get(f"/api/auth/entra/callback?code={code}&state={q['state'][0]}", follow_redirects=False)


def test_entra_sign_in_maps_groups(admin, fake_entra):
    client, csrf = admin
    claims, seen = fake_entra
    configure(client, csrf)
    client.post("/api/auth/logout", headers=csrf)
    assert client.get("/api/auth/status").json()["sso_enabled"]
    r = sign_in(client, seen)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    me = client.get("/api/auth/me").json()["user"]
    assert me["email"] == "reinder@example.org" and me["role"] == "admin" and me["auth_provider"] == "entra"
    # removed from the admin group in Microsoft 365 -> editor at the next sign-in
    client.post("/api/auth/logout", headers={"X-CSRF-Token": client.get("/api/auth/me").json()["csrf_token"]})
    claims["groups"] = ["g-editors"]
    sign_in(client, seen)
    assert client.get("/api/auth/me").json()["user"]["role"] == "editor"
    claims["groups"] = []
    client.post("/api/auth/logout", headers={"X-CSRF-Token": client.get("/api/auth/me").json()["csrf_token"]})
    sign_in(client, seen)
    assert client.get("/api/auth/me").json()["user"]["role"] == "staff"


def test_entra_links_local_admin_and_keeps_role(admin, fake_entra):
    client, csrf = admin
    claims, seen = fake_entra
    configure(client, csrf)
    claims.update(email="ADMIN@example.org", groups=[])
    client.post("/api/auth/logout", headers=csrf)
    sign_in(client, seen)
    me = client.get("/api/auth/me").json()["user"]
    assert me["email"] == "admin@example.org" and me["role"] == "admin" and me["auth_provider"] == "local"


def test_entra_rejects_bad_state_and_wrong_tenant(admin, fake_entra):
    client, csrf = admin
    claims, seen = fake_entra
    configure(client, csrf)
    client.post("/api/auth/logout", headers=csrf)
    r = client.get("/api/auth/entra/callback?code=x&state=forged", follow_redirects=False)
    assert r.headers["location"].startswith("/login?sso_error=sso_state_invalid")
    claims["tid"] = "99999999-2222-3333-4444-555555555555"
    r = sign_in(client, seen)
    assert "sso_error=sso_wrong_tenant" in r.headers["location"]
    assert client.get("/api/auth/me").status_code == 401


def test_entra_not_configured(client):
    r = client.get("/api/auth/entra/start", follow_redirects=False)
    assert r.headers["location"] == "/login?sso_error=sso_disabled"


def test_resolve_role():
    cfg = {"group_roles": {"admin": "A, B", "editor": "E"}, "default_role": "staff"}
    assert entra.resolve_role(cfg, ["b"], []) == "admin"
    assert entra.resolve_role(cfg, ["E", "B"], []) == "admin"
    assert entra.resolve_role(cfg, [], ["E"]) == "editor"
    assert entra.resolve_role(cfg, ["x"], []) == "staff"


def test_proxy_headers():
    import asyncio

    from stats_collector.proxy import ProxyHeadersMiddleware

    seen = {}

    async def app(scope, receive, send):
        seen.update(client=scope["client"][0], scheme=scope["scheme"])

    def run(peer, headers, **kw):
        mw = ProxyHeadersMiddleware(app, **kw)
        scope = {"type": "http", "client": (peer, 1), "scheme": "http",
                 "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
        asyncio.run(mw(scope, None, None))
        return seen["client"], seen["scheme"]

    hdrs = {"x-forwarded-for": "203.0.113.9, 104.23.172.14", "x-forwarded-proto": "https",
            "cf-connecting-ip": "198.51.100.7"}
    assert run("10.40.3.1", hdrs, trusted="127.0.0.1,10.40.3.0/24") == ("104.23.172.14", "https")
    assert run("10.40.3.1", hdrs, trusted="10.40.3.1", client_ip_header="CF-Connecting-IP") == ("198.51.100.7", "https")
    # not from a trusted proxy: headers are ignored
    assert run("192.0.2.5", hdrs, trusted="10.40.3.1", client_ip_header="CF-Connecting-IP") == ("192.0.2.5", "http")
