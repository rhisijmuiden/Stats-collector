"""Install a release from GitHub: backup, download, verify, migrate, switch, restart, health-check, rollback."""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import time
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url

from .. import build_info
from ..config import get_settings
from .ops import JobContext, JobFailed
from .updates import fetch_releases, parse_version

APP_USER = "statscollector"
SERVICES = ("stats-collector-web",)
KEEP_RELEASES = 3


def _db_name() -> str:
    return make_url(get_settings().database_url).database or "statscollector"


def _download(ctx: JobContext, url: str, dest: Path) -> None:
    ctx.log(f"downloading {url}")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _safe_extract(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")


def _health(port: int, expect_version: str, timeout_s: int = 90) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=5)
            if r.status_code == 200 and r.json().get("version") == expect_version:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def install_release_tree(ctx: JobContext, tarball: Path, version: str) -> Path:
    """Extract a release tarball into releases/<version> and build its virtualenv."""
    settings = get_settings()
    releases = settings.install_dir / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    target = releases / version
    staging = releases / f".{version}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    _safe_extract(tarball, staging)
    inner = staging / f"stats-collector-{version}"
    root = inner if inner.is_dir() else staging
    shutil.rmtree(target, ignore_errors=True)
    os.replace(root, target)
    shutil.rmtree(staging, ignore_errors=True)
    # The virtualenv is built in its final location (scripts and the editable install use absolute paths).
    try:
        ctx.run(["python3", "-m", "venv", str(target / "venv")])
        ctx.run([str(target / "venv/bin/pip"), "install", "--no-cache-dir", "--quiet", "-e", str(target / "backend")])
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def switch_current(target: Path) -> Path | None:
    install_dir = get_settings().install_dir
    current = install_dir / "current"
    previous = current.resolve() if current.is_symlink() else None
    tmp = install_dir / ".current.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(target)
    os.replace(tmp, current)
    return previous


def prune_releases(keep: set[Path]) -> None:
    releases = get_settings().install_dir / "releases"
    dirs = sorted(
        (p for p in releases.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in dirs[KEEP_RELEASES:]:
        if p.resolve() not in keep:
            shutil.rmtree(p, ignore_errors=True)


def run_update(ctx: JobContext, params: dict) -> dict:
    settings = get_settings()
    version = params["version"]
    current_version = build_info()["version"]
    if version == current_version:
        raise JobFailed(f"version {version} is already installed")
    release = next((r for r in fetch_releases(force=True) if r.version == version), None)
    if release is None or not release.asset_url or not release.checksum_url:
        raise JobFailed(f"release {version} not found or has no downloadable asset")
    ctx.log(f"updating {current_version} -> {version} ({release.channel})")

    work = settings.ops_dir / "downloads"
    work.mkdir(parents=True, exist_ok=True)
    tarball = work / f"stats-collector-{version}.tar.gz"
    checksum = work / f"stats-collector-{version}.tar.gz.sha256"
    _download(ctx, release.asset_url, tarball)
    _download(ctx, release.checksum_url, checksum)
    expected = checksum.read_text().split()[0].strip().lower()
    actual = _sha256(tarball)
    if expected != actual:
        raise JobFailed(f"checksum mismatch: expected {expected}, got {actual}")
    ctx.log("checksum ok")

    dump = settings.backup_dir / "pre-update" / f"{current_version}-to-{version}.dump"
    dump.parent.mkdir(parents=True, exist_ok=True)
    shutil.chown(dump.parent, user="postgres")
    ctx.run(["pg_dump", "-Fc", "-d", _db_name(), "-f", str(dump)], as_user="postgres")
    ctx.log(f"pre-update database dump: {dump}")

    target = install_release_tree(ctx, tarball, version)
    current_link = settings.install_dir / "current"
    old_root = current_link.resolve() if current_link.is_symlink() else None

    new_v, cur_v = parse_version(version), parse_version(current_version)
    downgrade = bool(new_v and cur_v and new_v < cur_v)
    try:
        if downgrade and old_root is not None:
            head = ctx.run([str(target / "venv/bin/stats-collector"), "db-head"], capture=True).stdout.strip()
            ctx.log(f"downgrade: migrating schema down to {head} with the current release")
            ctx.run([str(old_root / "venv/bin/stats-collector"), "migrate", "--to", head], as_user=APP_USER)
        else:
            ctx.run([str(target / "venv/bin/stats-collector"), "migrate"], as_user=APP_USER)
        previous = switch_current(target)
        for svc in SERVICES:
            ctx.run(["systemctl", "restart", svc])
        if not _health(settings.port, version):
            raise JobFailed("new version did not become healthy")
    except Exception as exc:
        ctx.log(f"update failed ({exc}); rolling back")
        for svc in SERVICES:
            ctx.run(["systemctl", "stop", svc], check=False)
        if old_root is not None:
            switch_current(old_root)
        ctx.run(
            ["pg_restore", "--clean", "--if-exists", "--single-transaction", "-d", _db_name(), str(dump)],
            as_user="postgres",
            check=False,
        )
        for svc in SERVICES:
            ctx.run(["systemctl", "restart", svc], check=False)
        raise
    prune_releases({target.resolve(), *([previous] if previous else [])})
    tarball.unlink(missing_ok=True)
    return {"from": current_version, "to": version, "downgrade": downgrade}
