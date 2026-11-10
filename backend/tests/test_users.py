def test_user_crud_and_roles(admin):
    client, csrf = admin
    r = client.post(
        "/api/users",
        json={"email": "staff@example.org", "display_name": "Staff", "role": "staff", "password": "s" * 12},
        headers=csrf,
    )
    assert r.status_code == 201
    uid = r.json()["id"]
    assert (
        client.post("/api/users", json={"email": "staff@example.org", "display_name": "x"}, headers=csrf).status_code
        == 409
    )
    assert client.patch(f"/api/users/{uid}", json={"role": "boss"}, headers=csrf).status_code == 400
    assert client.patch(f"/api/users/{uid}", json={"role": "editor"}, headers=csrf).json()["role"] == "editor"

    # the only admin cannot be demoted
    me = client.get("/api/auth/me").json()["user"]
    assert client.patch(f"/api/users/{me['id']}", json={"role": "staff"}, headers=csrf).json()["detail"] == "last_admin"

    # non-admins cannot reach admin endpoints
    client.post("/api/auth/logout", headers=csrf)
    login = client.post("/api/auth/login", json={"email": "staff@example.org", "password": "s" * 12})
    staff_csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/settings/email").status_code == 403
    assert client.put("/api/system/channel", json={"channel": "production"}, headers=staff_csrf).status_code == 403
    info = client.get("/api/system/info").json()
    assert "database" not in info and "build" in info
