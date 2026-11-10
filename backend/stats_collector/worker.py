"""Background worker (Celery) with an embedded scheduler (beat).

Started by the stats-collector-worker service:
    celery -A stats_collector.worker worker --beat --concurrency 4

Schedule:
    every 10 s   find sources whose poll interval has passed and poll them (Icecast, Owncast)
    every 5 min  roll samples up into hourly/daily/monthly metric points
    every 15 min sync YouTube channels that are due (every 3 hours; while importing history every run)
    daily        delete raw samples older than one year
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.schedules import crontab

from .config import get_settings
from .db import session_factory

log = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery("stats_collector", broker=settings.redis_url)
celery_app.conf.update(
    task_ignore_result=True,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    worker_prefetch_multiplier=1,
    task_acks_late=False,
    beat_schedule_filename=str(settings.data_dir / "celerybeat-schedule"),
    beat_schedule={
        "poll-due-sources": {"task": "stats_collector.poll_due", "schedule": 10.0, "options": {"expires": 9}},
        "rollup": {"task": "stats_collector.rollup", "schedule": 300.0, "options": {"expires": 290}},
        "youtube": {"task": "stats_collector.youtube_due", "schedule": 900.0, "options": {"expires": 880}},
        "meta": {"task": "stats_collector.meta_due", "schedule": 900.0, "options": {"expires": 880}},
        "threads": {"task": "stats_collector.threads_due", "schedule": 900.0, "options": {"expires": 880}},
        "x": {"task": "stats_collector.x_due", "schedule": 900.0, "options": {"expires": 880}},
        "social": {"task": "stats_collector.social_due", "schedule": 900.0, "options": {"expires": 880}},
        "links": {
            "task": "stats_collector.links",
            "schedule": crontab(minute="5,20,35,50"),
            "options": {"expires": 800},
        },
        "livewall": {"task": "stats_collector.livewall", "schedule": 60.0, "options": {"expires": 55}},
        "goals": {"task": "stats_collector.goals", "schedule": crontab(minute=40), "options": {"expires": 3000}},
        "prune-samples": {"task": "stats_collector.prune", "schedule": crontab(hour=3, minute=17)},
    },
)
app = celery_app  # `celery -A stats_collector.worker` looks for `app` or `celery`


@celery_app.task(name="stats_collector.poll_due")
def poll_due() -> int:
    from .services.collect import due_sources

    with session_factory()() as db:
        ids = [s.id for s in due_sources(db)]
    for source_id in ids:
        poll_one.apply_async((source_id,), expires=25)
    return len(ids)


@celery_app.task(name="stats_collector.poll_one")
def poll_one(source_id: int) -> bool:
    from .models import Source
    from .services.collect import poll_source

    with session_factory()() as db:
        source = db.get(Source, source_id)
        if source is None or not source.enabled:
            return False
        return poll_source(db, source) is not None


@celery_app.task(name="stats_collector.rollup")
def rollup_task() -> int:
    from .services.rollup import rollup

    with session_factory()() as db:
        return rollup(db)


@celery_app.task(name="stats_collector.prune")
def prune_task() -> int:
    from .services.rollup import prune_samples

    with session_factory()() as db:
        return prune_samples(db)


@celery_app.task(name="stats_collector.youtube_due")
def youtube_due() -> int:
    from .models import Source, utcnow
    from .services.youtube import is_due

    now = utcnow()
    with session_factory()() as db:
        ids = [
            s.id for s in db.query(Source).filter(Source.kind == "youtube", Source.enabled.is_(True)) if is_due(s, now)
        ]
    for source_id in ids:
        youtube_sync.apply_async((source_id,), expires=850)
    return len(ids)


@celery_app.task(name="stats_collector.youtube_sync")
def youtube_sync(source_id: int) -> dict | None:
    from .connectors import ConnectorError
    from .models import Source
    from .services import youtube

    with session_factory()() as db:
        source = db.get(Source, source_id)
        if source is None or not source.enabled:
            return None
        try:
            return youtube.sync(db, source)
        except ConnectorError as exc:
            log.warning("YouTube sync of source %s failed: %s", source_id, exc)
            return None


def youtube_soon(source_id: int) -> None:
    """Sync a YouTube channel in the background now (after connecting, or "sync now")."""
    try:
        youtube_sync.apply_async((source_id,), expires=600, retry=False)
    except Exception:  # noqa: BLE001 - Redis unreachable (development)
        log.warning("worker unreachable; YouTube source %s syncs at the next scheduled run", source_id)


@celery_app.task(name="stats_collector.meta_due")
def meta_due() -> int:
    from .models import Source, utcnow
    from .services.meta import KINDS, is_due

    now = utcnow()
    with session_factory()() as db:
        ids = [
            s.id for s in db.query(Source).filter(Source.kind.in_(KINDS), Source.enabled.is_(True)) if is_due(s, now)
        ]
    for source_id in ids:
        meta_sync.apply_async((source_id,), expires=850)
    return len(ids)


@celery_app.task(name="stats_collector.meta_sync")
def meta_sync(source_id: int) -> dict | None:
    from .connectors import ConnectorError
    from .models import Source
    from .services import meta

    with session_factory()() as db:
        source = db.get(Source, source_id)
        if source is None or not source.enabled:
            return None
        try:
            return meta.sync(db, source)
        except ConnectorError as exc:
            log.warning("Meta sync of source %s failed: %s", source_id, exc)
            return None


def meta_soon(source_id: int) -> None:
    """Sync a Facebook Page or Instagram account in the background now."""
    try:
        meta_sync.apply_async((source_id,), expires=600, retry=False)
    except Exception:  # noqa: BLE001 - Redis unreachable (development)
        log.warning("worker unreachable; Meta source %s syncs at the next scheduled run", source_id)


@celery_app.task(name="stats_collector.threads_due")
def threads_due() -> int:
    from .models import Source, utcnow
    from .services.threads import KINDS, is_due

    now = utcnow()
    with session_factory()() as db:
        ids = [
            s.id for s in db.query(Source).filter(Source.kind.in_(KINDS), Source.enabled.is_(True)) if is_due(s, now)
        ]
    for source_id in ids:
        threads_sync.apply_async((source_id,), expires=850)
    return len(ids)


@celery_app.task(name="stats_collector.threads_sync")
def threads_sync(source_id: int) -> dict | None:
    from .connectors import ConnectorError
    from .models import Source
    from .services import threads

    with session_factory()() as db:
        source = db.get(Source, source_id)
        if source is None or not source.enabled:
            return None
        try:
            return threads.sync(db, source)
        except ConnectorError as exc:
            log.warning("Threads sync of source %s failed: %s", source_id, exc)
            return None


def threads_soon(source_id: int) -> None:
    """Sync a Threads account in the background now."""
    try:
        threads_sync.apply_async((source_id,), expires=600, retry=False)
    except Exception:  # noqa: BLE001 - Redis unreachable (development)
        log.warning("worker unreachable; Threads source %s syncs at the next scheduled run", source_id)


@celery_app.task(name="stats_collector.x_due")
def x_due() -> int:
    from .models import Source, utcnow
    from .services.xcom import KINDS, is_due

    now = utcnow()
    with session_factory()() as db:
        ids = [
            s.id for s in db.query(Source).filter(Source.kind.in_(KINDS), Source.enabled.is_(True)) if is_due(s, now)
        ]
    for source_id in ids:
        x_sync.apply_async((source_id,), expires=850)
    return len(ids)


@celery_app.task(name="stats_collector.x_sync")
def x_sync(source_id: int) -> dict | None:
    from .connectors import ConnectorError
    from .models import Source
    from .services import xcom

    with session_factory()() as db:
        source = db.get(Source, source_id)
        if source is None or not source.enabled:
            return None
        try:
            return xcom.sync(db, source)
        except ConnectorError as exc:
            log.warning("X sync of source %s failed: %s", source_id, exc)
            return None


def x_soon(source_id: int) -> None:
    """Sync a X account in the background now."""
    try:
        x_sync.apply_async((source_id,), expires=600, retry=False)
    except Exception:  # noqa: BLE001 - Redis unreachable (development)
        log.warning("worker unreachable; X source %s syncs at the next scheduled run", source_id)


@celery_app.task(name="stats_collector.social_due")
def social_due() -> int:
    from .models import Source, utcnow
    from .services.social import KINDS, is_due

    now = utcnow()
    with session_factory()() as db:
        ids = [
            s.id for s in db.query(Source).filter(Source.kind.in_(KINDS), Source.enabled.is_(True)) if is_due(s, now)
        ]
    for source_id in ids:
        social_sync.apply_async((source_id,), expires=850)
    return len(ids)


@celery_app.task(name="stats_collector.social_sync")
def social_sync(source_id: int) -> dict | None:
    from .connectors import ConnectorError
    from .models import Source
    from .services import social

    with session_factory()() as db:
        source = db.get(Source, source_id)
        if source is None or not source.enabled:
            return None
        try:
            return social.sync(db, source)
        except ConnectorError as exc:
            log.warning("Sync of %s source %s failed: %s", source.kind, source_id, exc)
            return None


def social_soon(source_id: int) -> None:
    """Sync a Bluesky or Mastodon account in the background now."""
    try:
        social_sync.apply_async((source_id,), expires=600, retry=False)
    except Exception:  # noqa: BLE001 - Redis unreachable (development)
        log.warning("worker unreachable; source %s syncs at the next scheduled run", source_id)


@celery_app.task(name="stats_collector.goals")
def check_goals() -> int:
    """Goal emails: reached, or falling behind (at most once a week per goal)."""
    from .services.goals import check

    with session_factory()() as db:
        return check(db)


@celery_app.task(name="stats_collector.links")
def link_items() -> dict:
    """Link posts and videos to the articles they point to."""
    from .services.links import auto_link

    with session_factory()() as db:
        return auto_link(db)


@celery_app.task(name="stats_collector.livewall")
def livewall_task() -> int:
    """Live walls: one snapshot of the last hour per wall, read by the wall service on port 8081."""
    from .services.livewall import publish

    with session_factory()() as db:
        return publish(db)


def livewall_soon() -> None:
    """Refresh the walls now (after a change); inline when the worker is not reachable."""
    try:
        livewall_task.apply_async(expires=55, retry=False)
    except Exception:  # noqa: BLE001 - Redis unreachable (development)
        livewall_task()


def poll_soon(source_id: int) -> None:
    """Ask the worker to poll a source now (used by webhooks); falls back to polling inline."""
    try:
        poll_one.apply_async((source_id,), expires=60, retry=False)
    except Exception:  # noqa: BLE001 - Redis unreachable (development): poll inline
        poll_one(source_id)
