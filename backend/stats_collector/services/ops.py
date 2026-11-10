"""Privileged job queue.

The web process (unprivileged user ``statscollector``) only inserts rows into ``ops_jobs`` and touches a
trigger file. A root-owned systemd unit (``stats-collector-ops.service``, started by a ``.path`` unit) runs
``stats-collector ops run-pending`` which executes whitelisted job kinds with validated parameters.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import traceback
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_factory
from ..models import OpsJob, User, utcnow

JOB_KINDS = ("update", "backup", "restore", "verify_target")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-(?:rc|test)\.\d+)?$")
LABEL_RE = re.compile(r"^\d{8}-\d{6}-(full|incr)$")


class JobFailed(Exception):
    pass


def trigger_file() -> Path:
    return get_settings().ops_dir / "trigger"


def enqueue(db: Session, kind: str, params: dict, user: User | None) -> OpsJob:
    if kind not in JOB_KINDS:
        raise ValueError(kind)
    validate_params(kind, params)
    job = OpsJob(kind=kind, params=params, created_by=user.id if user else None)
    db.add(job)
    db.commit()
    try:
        path = trigger_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(job.id))
    except OSError:
        pass  # development without the ops directory; job stays queued
    return job


def validate_params(kind: str, params: dict) -> None:
    if kind == "update":
        if not VERSION_RE.match(str(params.get("version", ""))):
            raise ValueError("invalid_version")
    elif kind == "backup":
        if params.get("type") not in ("full", "incr"):
            raise ValueError("invalid_backup_type")
    elif kind == "restore":
        if not LABEL_RE.match(str(params.get("label", ""))):
            raise ValueError("invalid_label")
        if not isinstance(params.get("target_id"), int):
            raise ValueError("invalid_target")
    elif kind == "verify_target":
        if not isinstance(params.get("target_id"), int):
            raise ValueError("invalid_target")


class JobContext:
    """Passed to job handlers: logging that is flushed to the database, and command execution."""

    def __init__(self, db: Session, job: OpsJob):
        self.db = db
        self.job = job

    def log(self, line: str) -> None:
        stamp = utcnow().strftime("%H:%M:%S")
        entry = f"[{stamp}] {line}\n"
        try:  # file copy survives a database restore
            with open(get_settings().ops_dir / f"job-{self.job.id}.log", "a") as fh:
                fh.write(entry)
        except OSError:
            pass
        try:
            self.job.log = (self.job.log or "") + entry
            self.db.commit()
        except Exception:  # noqa: BLE001 - database may be unavailable during a restore
            self.db.rollback()

    def run(
        self,
        cmd: list[str],
        *,
        as_user: str | None = None,
        env: dict | None = None,
        check: bool = True,
        capture: bool = False,
        stdout_path: Path | None = None,
        secret_args: tuple[str, ...] = (),
        timeout: int = 3600,
    ) -> subprocess.CompletedProcess:
        full = cmd if not as_user else ["runuser", "-u", as_user, "--", *cmd]
        shown = " ".join(shlex.quote("***" if a in secret_args else a) for a in full)
        self.log("$ " + shown)
        run_env = {**os.environ, **(env or {})}
        if stdout_path is not None:
            with open(stdout_path, "wb") as fh:
                proc = subprocess.run(full, stdout=fh, stderr=subprocess.PIPE, env=run_env, timeout=timeout)
            out = ""
        else:
            proc = subprocess.run(full, capture_output=True, text=True, env=run_env, timeout=timeout)
            out = proc.stdout or ""
        err = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode(errors="replace")
        if out and not capture:
            self.log(out.strip()[-4000:])
        if err:
            self.log(err.strip()[-4000:])
        if check and proc.returncode != 0:
            raise JobFailed(f"command failed with exit code {proc.returncode}: {cmd[0]}")
        return proc


def _handlers() -> dict[str, Callable[[JobContext, dict], dict]]:
    from . import backup, updater

    return {
        "update": updater.run_update,
        "backup": backup.run_backup,
        "restore": backup.run_restore,
        "verify_target": backup.run_verify_target,
    }


def run_job(db: Session, job: OpsJob) -> None:
    ctx = JobContext(db, job)
    job.status = "running"
    job.started_at = utcnow()
    db.commit()
    try:
        validate_params(job.kind, job.params or {})
        result = _handlers()[job.kind](ctx, job.params or {})
        job = ctx.job
        job.result = result or {}
        job.status = "succeeded"
        ctx.log("done")
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded on the job
        db.rollback()
        job = db.get(OpsJob, job.id) or job
        ctx.job = job
        job.status = "failed"
        job.result = {"error": str(exc)}
        ctx.log("FAILED: " + str(exc))
        if not isinstance(exc, JobFailed):
            ctx.log(traceback.format_exc()[-3000:])
    job.finished_at = utcnow()
    db.commit()
    write_status_file(job)


def write_status_file(job: OpsJob) -> None:
    """Keep the last result outside the database (survives a database restore)."""
    try:
        path = get_settings().ops_dir / f"last-{job.kind}.json"
        path.write_text(
            json.dumps(
                {
                    "id": job.id,
                    "kind": job.kind,
                    "status": job.status,
                    "params": job.params,
                    "result": job.result,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                }
            )
        )
    except OSError:
        pass


def run_pending() -> int:
    """Run every queued job once, oldest first. Returns the number of jobs processed."""
    count = 0
    factory = session_factory()
    while True:
        with factory() as db:
            job = db.execute(
                select(OpsJob).where(OpsJob.status == "queued").order_by(OpsJob.id).limit(1)
            ).scalar_one_or_none()
            if job is None:
                return count
            run_job(db, job)
            count += 1
