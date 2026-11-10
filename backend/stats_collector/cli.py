"""Command line: ``stats-collector <command>``."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from . import APP_ROOT, build_info


def _alembic_config():
    from alembic.config import Config

    from .config import get_settings

    cfg = Config()
    cfg.set_main_option("script_location", str(APP_ROOT / "backend" / "stats_collector" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    return cfg


def cmd_migrate(args) -> int:
    from alembic import command

    cfg = _alembic_config()
    if args.to:
        command.downgrade(cfg, args.to)
    else:
        command.upgrade(cfg, "head")
    return 0


def cmd_db_head(_args) -> int:
    from alembic.script import ScriptDirectory

    print(ScriptDirectory.from_config(_alembic_config()).get_current_head())
    return 0


def cmd_setup_link(args) -> int:
    from sqlalchemy import func, select

    from .api.auth import create_setup_token
    from .config import get_settings
    from .db import session_factory
    from .models import User

    with session_factory()() as db:
        if db.execute(select(func.count()).select_from(User)).scalar_one() > 0 and not args.force:
            print("An account already exists. Use --force to create a link anyway.", file=sys.stderr)
            return 1
        token = create_setup_token(db, hours=args.hours)
    print(f"{get_settings().public_url.rstrip('/')}/setup?token={token}")
    return 0


def cmd_reset_password(args) -> int:
    import getpass

    from sqlalchemy import func, select

    from .db import session_factory
    from .models import User
    from .security import hash_password, password_problems

    with session_factory()() as db:
        user = db.execute(select(User).where(func.lower(User.email) == args.email.lower())).scalar_one_or_none()
        if user is None:
            print("No such user", file=sys.stderr)
            return 1
        pw = getpass.getpass("New password: ")
        if password_problems(pw):
            print("Password must be at least 12 characters", file=sys.stderr)
            return 1
        user.password_hash = hash_password(pw)
        user.totp_secret = None
        db.commit()
    print("Password reset; two-factor authentication disabled for this account.")
    return 0


def cmd_ops(args) -> int:
    from .services import ops

    if args.action == "run-pending":
        n = ops.run_pending()
        print(f"processed {n} job(s)")
    elif args.action == "tick":
        scheduled_tick()
        ops.run_pending()
    return 0


def scheduled_tick(now: datetime | None = None) -> str | None:
    """Called hourly by stats-collector-backup.timer: enqueue a scheduled backup when one is due."""
    from sqlalchemy import select

    from .db import session_factory
    from .models import BackupRecord, OpsJob
    from .services import ops, settings_store

    with session_factory()() as db:
        cfg = settings_store.get_section(db, "backup")
        if not cfg.get("schedule_enabled"):
            return None
        if db.execute(select(OpsJob).where(OpsJob.status.in_(("queued", "running")))).first():
            return None
        tz = ZoneInfo(settings_store.get_section(db, "general").get("timezone") or "Europe/Amsterdam")
        now = (now or datetime.now(UTC)).astimezone(tz)
        kind = due_backup(cfg, db.execute(select(BackupRecord)).scalars().all(), now)
        if kind:
            ops.enqueue(db, "backup", {"type": kind, "scheduled": True}, None)
        return kind


def due_backup(cfg: dict, records, now: datetime) -> str | None:
    def aware(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    fulls = sorted((aware(r.created_at) for r in records if r.kind == "full"), reverse=True)
    latest = max((aware(r.created_at) for r in records), default=None)
    hour = int(cfg.get("time", "02:30").split(":")[0])
    period = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=28)}[
        cfg.get("full_every", "weekly")
    ]
    slack = timedelta(hours=2)
    if not fulls:
        return "full"
    if now.hour == hour and now - fulls[0] >= period - slack:
        if cfg.get("full_every") != "weekly" or now.weekday() == int(cfg.get("full_weekday", 6)):
            return "full"
    if now - fulls[0] > period + timedelta(days=1):
        return "full"  # overdue (e.g. server was off at the scheduled time)
    if latest and now - latest >= timedelta(hours=int(cfg.get("incremental_every_hours", 24))) - slack:
        if int(cfg.get("incremental_every_hours", 24)) < 24 or now.hour == hour:
            return "incr"
    return None


def cmd_version(_args) -> int:
    info = build_info()
    print(
        f"Stats Collector {info['version']} (channel {info.get('channel') or '-'}, commit {info.get('commit') or '-'})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stats-collector")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("migrate", help="Apply database migrations")
    p.add_argument("--to", help="Downgrade to this revision instead of upgrading")
    p.set_defaults(func=cmd_migrate)
    sub.add_parser("db-head", help="Print the newest migration revision").set_defaults(func=cmd_db_head)

    p = sub.add_parser("setup-link", help="Print a one-time link to create the first admin")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_setup_link)

    p = sub.add_parser("reset-password", help="Reset a local account password")
    p.add_argument("email")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("ops", help="Run privileged jobs (root only)")
    p.add_argument("action", choices=["run-pending", "tick"])
    p.set_defaults(func=cmd_ops)

    sub.add_parser("version").set_defaults(func=cmd_version)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
