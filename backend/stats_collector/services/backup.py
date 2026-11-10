"""Full and incremental backups to FTP, FTPS and SFTP/SCP targets, and restore from a remote target.

Layout of the local backup directory (mirrored 1:1 to every remote target with ``rclone sync``)::

    backup/
      pgbackrest/          pgBackRest repository (database, full + incremental)
      files/<label>.tar.gz files (uploads, branding, config), GNU tar incremental chain
      files/<label>.snar   tar snapshot after that backup
      manifests/<label>.json

Remote copies are encrypted client-side with an rclone ``crypt`` layer when a passphrase is configured.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import build_info
from ..config import CONFIG_FILE, get_settings
from ..models import BackupRecord, BackupTarget, utcnow
from ..security import decrypt_secret
from . import settings_store
from .ops import JobContext, JobFailed

DEFAULT_PORTS = {"ftp": 21, "ftps": 21, "sftp": 22}
APP_SERVICES = ("stats-collector-web",)


# --- rclone configuration ------------------------------------------------------------------------------


def obscure(value: str) -> str:
    """rclone stores passwords 'obscured' in its config file."""
    out = subprocess.run(["rclone", "obscure", "-"], input=value, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def known_hosts_file() -> Path:
    return get_settings().data_dir / "ssh_known_hosts"


def rclone_sections(target: BackupTarget, passphrase: str | None, obscure_fn=obscure) -> str:
    """Build an rclone config for a target. Remote name is always ``dest``."""
    secret = decrypt_secret(target.secret_enc) or ""
    port = target.port or DEFAULT_PORTS[target.kind]
    lines = ["[base]"]
    if target.kind in ("ftp", "ftps"):
        lines += ["type = ftp", f"host = {target.host}", f"port = {port}", f"user = {target.username}"]
        if secret:
            lines.append(f"pass = {obscure_fn(secret)}")
        if target.kind == "ftps":
            lines.append("tls = true" if target.ftps_mode == "implicit" else "explicit_tls = true")
            if not target.verify_tls:
                lines.append("no_check_certificate = true")
    elif target.kind == "sftp":
        lines += ["type = sftp", f"host = {target.host}", f"port = {port}", f"user = {target.username}"]
        if target.auth_method == "key":
            lines.append("key_pem = " + secret.strip().replace("\r", "").replace("\n", "\\n"))
        elif secret:
            lines.append(f"pass = {obscure_fn(secret)}")
        if known_hosts_file().exists():
            lines.append(f"known_hosts_file = {known_hosts_file()}")
        lines.append("shell_type = unix")
    else:  # pragma: no cover - validated by the API
        raise JobFailed(f"unsupported target kind {target.kind}")
    path = target.path.strip("/") or "stats-collector"
    if passphrase:
        lines += [
            "",
            "[dest]",
            "type = crypt",
            f"remote = base:{path}",
            f"password = {obscure_fn(passphrase)}",
            "filename_encryption = off",
            "directory_name_encryption = false",
        ]
    else:
        lines += ["", "[dest]", "type = alias", f"remote = base:{path}"]
    return "\n".join(lines) + "\n"


@contextmanager
def rclone_config(target: BackupTarget, passphrase: str | None):
    fd, name = tempfile.mkstemp(prefix="sc-rclone-", suffix=".conf")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(rclone_sections(target, passphrase))
        os.chmod(name, 0o600)
        yield name
    finally:
        os.unlink(name)


def _passphrase(db: Session) -> str | None:
    return decrypt_secret(settings_store.get_section(db, "backup").get("encryption_passphrase_enc"))


def _rclone(ctx: JobContext, conf: str, *args: str, capture: bool = False):
    return ctx.run(["rclone", "--config", conf, "--retries", "3", "--low-level-retries", "5", *args], capture=capture)


# --- helpers -------------------------------------------------------------------------------------------


def new_label(kind: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.strftime("%Y%m%d-%H%M%S") + f"-{kind}"


def manifests_in(directory: Path) -> list[dict]:
    out = []
    if directory.is_dir():
        for p in sorted(directory.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except ValueError:
                continue
    return out


def manifests(backup_dir: Path) -> list[dict]:
    return manifests_in(backup_dir / "manifests")


def chain_for(label: str, all_manifests: list[dict]) -> list[dict]:
    """Return the full backup plus all incrementals up to and including ``label``."""
    by_label = {m["label"]: m for m in all_manifests}
    if label not in by_label:
        raise JobFailed(f"backup {label} not found")
    chain = [by_label[label]]
    while chain[-1]["kind"] == "incr":
        base = chain[-1].get("base")
        if base not in by_label:
            raise JobFailed(f"backup chain broken: base {base} of {chain[-1]['label']} missing")
        chain.append(by_label[base])
    return list(reversed(chain))


def _file_sources() -> list[str]:
    settings = get_settings()
    sources = []
    if settings.uploads_dir.exists():
        sources.append(str(settings.uploads_dir))
    if Path(CONFIG_FILE).exists():
        sources.append(CONFIG_FILE)
    return sources


def _pgbackrest(ctx: JobContext, *args: str, capture: bool = False):
    settings = get_settings()
    return ctx.run(["pgbackrest", f"--stanza={settings.pgbackrest_stanza}", *args], as_user="postgres", capture=capture)


def _latest_pgbackrest_label(ctx: JobContext) -> str:
    out = _pgbackrest(ctx, "--output=json", "info", capture=True).stdout
    data = json.loads(out or "[]")
    backups = data[0].get("backup", []) if data else []
    if not backups:
        raise JobFailed("pgBackRest reports no backups")
    return backups[-1]["label"]


# --- backup --------------------------------------------------------------------------------------------


def run_backup(ctx: JobContext, params: dict) -> dict:
    settings = get_settings()
    db = ctx.db
    cfg = settings_store.get_section(db, "backup")
    kind = params["type"]
    bdir = settings.backup_dir
    for sub in ("files", "manifests"):
        (bdir / sub).mkdir(parents=True, exist_ok=True)

    existing = manifests(bdir)
    last_full = next((m for m in reversed(existing) if m["kind"] == "full"), None)
    if kind == "incr" and last_full is None:
        ctx.log("no full backup yet; running a full backup instead")
        kind = "full"
    label = new_label(kind)
    base = existing[-1]["label"] if kind == "incr" and existing else None

    retention = max(1, int(cfg.get("retention_full", 4)))
    _pgbackrest(ctx, f"--type={kind}", f"--repo1-retention-full={retention}", "backup")
    pg_label = _latest_pgbackrest_label(ctx)

    files_tar = bdir / "files" / f"{label}.tar.gz"
    snar = bdir / "files" / f"{label}.snar"
    if kind == "incr" and base and (bdir / "files" / f"{base}.snar").exists():
        shutil.copy2(bdir / "files" / f"{base}.snar", snar)
    sources = _file_sources() if cfg.get("include_uploads", True) else [CONFIG_FILE]
    sources = [s for s in sources if Path(s).exists()]
    if sources:
        ctx.run(["tar", "--create", "--gzip", f"--listed-incremental={snar}", "-f", str(files_tar), *sources])
    size = sum(p.stat().st_size for p in (files_tar,) if p.exists())

    manifest = {
        "label": label,
        "kind": kind,
        "base": base,
        "pgbackrest_label": pg_label,
        "files": files_tar.name if files_tar.exists() else None,
        "created_at": utcnow().isoformat(),
        "app_version": build_info()["version"],
    }
    (bdir / "manifests" / f"{label}.json").write_text(json.dumps(manifest, indent=2))
    _apply_file_retention(ctx, bdir, retention)

    uploaded = []
    passphrase = _passphrase(db)
    targets = db.execute(select(BackupTarget).where(BackupTarget.enabled.is_(True))).scalars().all()
    for target in targets:
        with rclone_config(target, passphrase) as conf:
            _rclone(ctx, conf, "sync", str(bdir), "dest:", "--exclude", "pre-update/**", "--exclude", "*.lock")
        uploaded.append(target.name)
        ctx.log(f"uploaded to {target.name}")
    if not targets:
        ctx.log("warning: no remote backup targets configured; backup kept locally only")

    db.add(
        BackupRecord(
            label=label,
            kind=kind,
            base_label=base,
            size_bytes=size,
            targets=uploaded,
            app_version=manifest["app_version"],
        )
    )
    db.commit()
    return {"label": label, "kind": kind, "targets": uploaded}


def _apply_file_retention(ctx: JobContext, bdir: Path, retention_full: int) -> None:
    all_m = manifests(bdir)
    fulls = [m for m in all_m if m["kind"] == "full"]
    if len(fulls) <= retention_full:
        return
    cutoff = fulls[-retention_full]["label"]
    for m in all_m:
        if m["label"] < cutoff:
            for name in (f"{m['label']}.tar.gz", f"{m['label']}.snar"):
                (bdir / "files" / name).unlink(missing_ok=True)
            (bdir / "manifests" / f"{m['label']}.json").unlink(missing_ok=True)
            ctx.log(f"retention: removed {m['label']}")


# --- remote listing and restore -----------------------------------------------------------------------


def run_verify_target(ctx: JobContext, params: dict) -> dict:
    target = ctx.db.get(BackupTarget, params["target_id"])
    if target is None:
        raise JobFailed("target not found")
    if target.kind == "sftp":
        port = str(target.port or 22)
        keys = ctx.run(["ssh-keyscan", "-p", port, target.host], capture=True, check=False).stdout
        if keys:
            khf = known_hosts_file()
            existing = khf.read_text() if khf.exists() else ""
            new = [ln for ln in keys.splitlines() if ln and ln not in existing]
            if new:
                with open(khf, "a") as fh:
                    fh.write("\n".join(new) + "\n")
                ctx.log(f"stored {len(new)} host key(s) for {target.host}")
    with rclone_config(target, _passphrase(ctx.db)) as conf:
        _rclone(ctx, conf, "mkdir", "dest:manifests")
        listing = _rclone(ctx, conf, "lsjson", "dest:manifests", capture=True).stdout
    names = sorted(f["Name"] for f in json.loads(listing or "[]") if f["Name"].endswith(".json"))
    remote: list[dict] = []
    if names:
        with tempfile.TemporaryDirectory() as tmp, rclone_config(target, _passphrase(ctx.db)) as conf:
            _rclone(ctx, conf, "copy", "dest:manifests", tmp)
            remote = manifests_in(Path(tmp))
    return {"ok": True, "remote_backups": remote}


def run_restore(ctx: JobContext, params: dict) -> dict:
    settings = get_settings()
    db = ctx.db
    target = db.get(BackupTarget, params["target_id"])
    if target is None:
        raise JobFailed("target not found")
    label = params["label"]
    bdir = settings.backup_dir
    passphrase = _passphrase(db)
    target_name = target.name

    ctx.log(f"fetching backup repository from {target_name}")
    with rclone_config(target, passphrase) as conf:
        _rclone(ctx, conf, "sync", "dest:", str(bdir), "--exclude", "pre-update/**")
    ctx.run(["chown", "-R", "postgres:postgres", str(bdir / "pgbackrest")])

    chain = chain_for(label, manifests(bdir))
    point = chain[-1]
    ctx.log("restore chain: " + " -> ".join(m["label"] for m in chain))
    info = _pgbackrest(ctx, "--output=json", "info", capture=True).stdout
    if point["pgbackrest_label"] not in info:
        raise JobFailed(f"database backup {point['pgbackrest_label']} missing from the repository")
    for m in chain:
        if m.get("files"):
            ctx.run(["tar", "--list", "--gzip", "-f", str(bdir / "files" / m["files"])], capture=True)
    ctx.log("verification ok")

    # Everything below runs without the web app; the database is replaced, so the job row is too.
    db.close()
    for svc in APP_SERVICES:
        ctx.run(["systemctl", "stop", svc], check=False)
    ctx.run(["systemctl", "stop", "postgresql"])
    try:
        _pgbackrest(
            ctx,
            "--delta",
            f"--set={point['pgbackrest_label']}",
            "--type=immediate",
            "--target-action=promote",
            "restore",
        )
    finally:
        ctx.run(["systemctl", "start", "postgresql"])
    for m in chain:
        if m.get("files"):
            ctx.run(
                [
                    "tar",
                    "--extract",
                    "--gzip",
                    "--listed-incremental=/dev/null",
                    "-f",
                    str(bdir / "files" / m["files"]),
                    "-C",
                    "/",
                ]
            )
    for svc in APP_SERVICES:
        ctx.run(["systemctl", "start", svc], check=False)
    return {"label": label, "target": target_name, "chain": [m["label"] for m in chain]}
