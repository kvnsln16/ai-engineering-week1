from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.scheduler.jobs import run_all_collectors

logger = logging.getLogger(__name__)

SCHEDULE = {
    "hour": 6,
    "minute": 0,
    "timezone": "Asia/Manila",
}

MISFIRE_GRACE_TIME = 60 * 60


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=SCHEDULE["timezone"])

    trigger = CronTrigger(
        hour=SCHEDULE["hour"],
        minute=SCHEDULE["minute"],
        timezone=SCHEDULE["timezone"],
    )

    scheduler.add_job(
        run_all_collectors,
        trigger=trigger,
        id="daily_signal_collection",
        name="Daily signal collection (all connectors)",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_TIME,
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler

    next_run = scheduler.get_job("daily_signal_collection").next_run_time
    logger.info(
        "scheduler: started; next run at %s (%s)",
        next_run.isoformat(), SCHEDULE["timezone"],
    )
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler: stopped")
    _scheduler = None
