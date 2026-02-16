from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.stock_mvp.core.rules import load_rules
from app.stock_mvp.services.pipeline import PipelineService

_scheduler: BackgroundScheduler | None = None


def _trigger_from_cron(cron_expr: str, timezone: str) -> CronTrigger:
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron format (expected 5 fields): {cron_expr}")
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=timezone,
    )


def start_scheduler(pipeline_service: PipelineService) -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    rules = load_rules()
    schedules = rules.get("schedules", {})
    tz = schedules.get("timezone", "Asia/Kolkata")

    full_scan_cron = schedules.get("full_scan_cron", "30 16 * * 1-5")
    event_scan_cron = schedules.get("event_scan_cron", "*/30 9-15 * * 1-5")

    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        lambda: pipeline_service.run_scan(run_type="scheduled_full_scan"),
        trigger=_trigger_from_cron(full_scan_cron, tz),
        id="full_scan_job",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        lambda: pipeline_service.run_scan(run_type="scheduled_event_scan"),
        trigger=_trigger_from_cron(event_scan_cron, tz),
        id="event_scan_job",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def reload_scheduler(pipeline_service: PipelineService) -> BackgroundScheduler:
    stop_scheduler()
    return start_scheduler(pipeline_service)
