from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from stats_collector.cli import due_backup
from stats_collector.services import backup, ops


def test_validate_params():
    ops.validate_params("update", {"version": "0.2.0-rc.3"})
    with pytest.raises(ValueError):
        ops.validate_params("update", {"version": "1.0; rm -rf /"})
    with pytest.raises(ValueError):
        ops.validate_params("restore", {"label": "../x", "target_id": 1})
    ops.validate_params("restore", {"label": "20261110-023000-incr", "target_id": 1})


def test_rclone_config(app_env):
    from stats_collector.models import BackupTarget
    from stats_collector.security import encrypt_secret

    t = BackupTarget(
        name="nas",
        kind="ftps",
        host="nas.local",
        port=None,
        username="u",
        secret_enc=encrypt_secret("pw"),
        path="/backups/sc/",
        ftps_mode="implicit",
        verify_tls=False,
        auth_method="password",
    )
    conf = backup.rclone_sections(t, "passphrase-123", obscure_fn=lambda s: f"OBS({s})")
    assert "type = ftp" in conf and "tls = true" in conf and "no_check_certificate = true" in conf
    assert "pass = OBS(pw)" in conf and "port = 21" in conf
    assert "type = crypt" in conf and "remote = base:backups/sc" in conf
    t2 = BackupTarget(
        name="ssh",
        kind="sftp",
        host="h",
        port=2222,
        username="u",
        path="",
        secret_enc=encrypt_secret("-----BEGIN KEY-----\nabc\n-----END KEY-----\n"),
        auth_method="key",
        ftps_mode="explicit",
        verify_tls=True,
    )
    conf2 = backup.rclone_sections(t2, None, obscure_fn=lambda s: s)
    assert "key_pem = -----BEGIN KEY-----\\nabc\\n-----END KEY-----" in conf2
    assert "type = alias" in conf2 and "remote = base:stats-collector" in conf2


def test_chain_for():
    ms = [
        {"label": "20261101-023000-full", "kind": "full", "base": None},
        {"label": "20261102-023000-incr", "kind": "incr", "base": "20261101-023000-full"},
        {"label": "20261103-023000-incr", "kind": "incr", "base": "20261102-023000-incr"},
    ]
    chain = backup.chain_for("20261103-023000-incr", ms)
    assert [m["label"] for m in chain] == [m["label"] for m in ms]
    with pytest.raises(ops.JobFailed):
        backup.chain_for("20261103-023000-incr", ms[1:])


def _rec(kind, dt):
    return SimpleNamespace(kind=kind, created_at=dt)


def test_due_backup():
    cfg = {"full_every": "weekly", "full_weekday": 6, "incremental_every_hours": 24, "time": "02:30"}
    sunday_2am = datetime(2026, 11, 15, 2, 5, tzinfo=UTC)
    assert due_backup(cfg, [], sunday_2am) == "full"
    recs = [_rec("full", sunday_2am - timedelta(days=7))]
    assert due_backup(cfg, recs, sunday_2am) == "full"
    recs = [_rec("full", sunday_2am - timedelta(days=3))]
    assert due_backup(cfg, recs, sunday_2am) == "incr"
    assert due_backup(cfg, recs, sunday_2am.replace(hour=14)) is None
    recs = [_rec("full", sunday_2am - timedelta(days=3)), _rec("incr", sunday_2am - timedelta(hours=1))]
    assert due_backup(cfg, recs, sunday_2am) is None


def test_backup_api_enqueue(admin):
    client, csrf = admin
    t = client.post(
        "/api/backup/targets",
        json={"name": "nas", "kind": "sftp", "host": "nas.local", "username": "u", "secret": "pw"},
        headers=csrf,
    )
    assert t.status_code == 201 and t.json()["secret_set"] is True
    bad = client.post(
        "/api/backup/targets", json={"name": "x", "kind": "sftp", "host": "a b;c", "username": "u"}, headers=csrf
    )
    assert bad.status_code == 422
    job = client.post("/api/backup/run", json={"type": "full"}, headers=csrf)
    assert job.status_code == 202 and job.json()["status"] == "queued"
    assert client.post("/api/backup/run", json={"type": "incr"}, headers=csrf).status_code == 409
    r = client.post(
        "/api/backup/restore",
        json={"target_id": t.json()["id"], "label": "20261110-023000-full", "confirm": "no"},
        headers=csrf,
    )
    assert r.status_code == 400


def test_run_job_records_failure(app_env, monkeypatch):
    from stats_collector.db import session_factory
    from stats_collector.models import OpsJob

    def explode(ctx, params):
        ctx.log("starting")
        raise ops.JobFailed("boom")

    monkeypatch.setattr(ops, "_handlers", lambda: {"backup": explode})
    with session_factory()() as db:
        job = ops.enqueue(db, "backup", {"type": "full"}, None)
        job_id = job.id
    assert ops.run_pending() == 1
    with session_factory()() as db:
        job = db.get(OpsJob, job_id)
        assert job.status == "failed" and "boom" in job.log and "starting" in job.log


def test_poke_runner_replaces_trigger_owned_by_someone_else(app_env):
    path = ops.trigger_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1")
    path.chmod(0o444)  # like a trigger left behind by root: not writable in place
    assert ops.poke_runner(7)
    assert path.read_text() == "7"
    assert [p.name for p in path.parent.iterdir() if p.name.startswith(".trigger")] == []
