from __future__ import annotations

import os

import pytest

os.environ["SC_CONFIG_FILE"] = "/nonexistent"


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    # SC_TEST_DATABASE_URL runs the tests against an empty PostgreSQL database instead of SQLite.
    pg = os.environ.get("SC_TEST_DATABASE_URL")
    if pg:
        from sqlalchemy import create_engine, text

        engine = create_engine(pg)
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        engine.dispose()
    monkeypatch.setenv("SC_DATABASE_URL", pg or f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SC_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("SC_SECRET_KEY", "test-secret")
    from stats_collector import db
    from stats_collector.config import get_settings
    from stats_collector.security import login_limiter

    get_settings.cache_clear()
    db.reset_engine()
    login_limiter.hits.clear()
    from stats_collector.cli import main

    assert main(["migrate"]) == 0
    yield tmp_path
    db.reset_engine()
    get_settings.cache_clear()


@pytest.fixture()
def client(app_env):
    from fastapi.testclient import TestClient

    from stats_collector.main import create_app

    with TestClient(create_app()) as c:
        yield c


def make_token():
    from stats_collector.api.auth import create_setup_token
    from stats_collector.db import session_factory

    with session_factory()() as s:
        return create_setup_token(s)


@pytest.fixture()
def admin(client):
    """Creates the first admin through the setup flow and returns (client, csrf headers)."""
    r = client.post(
        "/api/auth/setup",
        json={
            "token": make_token(),
            "email": "admin@example.org",
            "display_name": "Admin",
            "password": "correct horse battery",
            "language": "nl",
        },
    )
    assert r.status_code == 200, r.text
    return client, {"X-CSRF-Token": r.json()["csrf_token"]}
