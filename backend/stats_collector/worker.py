"""Background worker (Celery) with an embedded scheduler (beat).

Started by the stats-collector-worker service:
    celery -A stats_collector.worker worker --beat --concurrency 4

Schedule:
    every 10 s   find sources whose poll interval has passed and poll them (Icecast, Owncast)
    every 5 min  roll samples up into hourly/daily/monthly metric points
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


def poll_soon(source_id: int) -> None:
    """Ask the worker to poll a source now (used by webhooks); falls back to polling inline."""
    try:
        poll_one.apply_async((source_id,), expires=60, retry=False)
    except Exception:  # noqa: BLE001 - Redis unreachable (development): poll inline
        poll_one(source_id)
