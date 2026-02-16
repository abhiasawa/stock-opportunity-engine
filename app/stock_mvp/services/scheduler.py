from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.stock_mvp.core.rules import load_rules
from app.stock_mvp.services.pipeline import PipelineService

logger = logging.getLogger(__name__)
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


def _run_price_refresh() -> None:
    """Quick price-only refresh — updates cached prices without full fundamentals scan."""
    from app.stock_mvp.services.factories import build_provider
    from app.stock_mvp.providers.india_live_provider import IndiaLiveProvider

    rules = load_rules()
    provider = build_provider(rules)

    if not isinstance(provider, IndiaLiveProvider):
        return

    symbols = provider._load_symbols()
    if not symbols:
        return

    prices = provider._batch_fetch_prices(symbols)
    logger.info("Price refresh: updated %d prices", len(prices))


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

    # Full scan — daily after market close
    scheduler.add_job(
        lambda: pipeline_service.run_scan_background(run_type="scheduled_full_scan"),
        trigger=_trigger_from_cron(full_scan_cron, tz),
        id="full_scan_job",
        replace_existing=True,
        max_instances=1,
    )

    # Event scan — periodic during market hours
    scheduler.add_job(
        lambda: pipeline_service.run_scan_background(run_type="scheduled_event_scan"),
        trigger=_trigger_from_cron(event_scan_cron, tz),
        id="event_scan_job",
        replace_existing=True,
        max_instances=1,
    )

    # Price refresh — every 15 minutes during market hours (9:00-15:30 IST, weekdays)
    scheduler.add_job(
        _run_price_refresh,
        trigger=CronTrigger(minute="*/15", hour="9-15", day_of_week="mon-fri", timezone=tz),
        id="price_refresh_job",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started: full scan [%s], events [%s], prices [every 15 min market hours]",
                full_scan_cron, event_scan_cron)
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def reload_scheduler(pipeline_service: PipelineService) -> BackgroundScheduler:
    stop_scheduler()
    return start_scheduler(pipeline_service)
