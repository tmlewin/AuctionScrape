"""
APScheduler v4 integration for ProcureWatch.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta
from uuid import uuid4

from apscheduler import AsyncScheduler, ConflictPolicy
from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from procurewatch.core.config.loader import load_all_portal_configs
from procurewatch.core.logging import get_logger
from procurewatch.core.orchestrator.runner import run_portal_scrape
from procurewatch.core.scheduler.locks import LockManager
from procurewatch.persistence.db import get_async_session, get_session
from procurewatch.persistence.models import ScheduledJob

logger = get_logger("scheduler")


async def execute_scheduled_job(job_name: str, holder_id: str) -> None:
    """Execute a scheduled scrape job."""
    async with get_async_session() as session:
        stmt = select(ScheduledJob).where(ScheduledJob.name == job_name)
        job = (await session.execute(stmt)).scalar_one_or_none()

        if job is None or not job.enabled:
            logger.warning("Scheduled job not found or disabled: %s", job_name)
            return

        portals = _coerce_portals(job.portals_json)
        if not portals:
            portals = list(load_all_portal_configs().keys())

        if not portals:
            logger.warning("No portals configured for scheduled job: %s", job_name)
            return

        ttl_minutes = job.max_runtime_minutes or 120
        lock_name = f"schedule:{job.name}"

    with get_session() as session:
        lock_manager = LockManager(session)
        if not lock_manager.acquire(lock_name, holder_id, ttl_minutes=ttl_minutes):
            logger.info("Lock held, skipping run for %s", job_name)
            return

    status = "COMPLETED"
    try:
        for portal_name in portals:
            await run_portal_scrape(portal_name, run_type="scheduled")
    except Exception:
        status = "FAILED"
        logger.exception("Scheduled job failed: %s", job_name)
        await _update_job_status(job_name, status)
        raise
    else:
        await _update_job_status(job_name, status)
    finally:
        with get_session() as session:
            lock_manager = LockManager(session)
            lock_manager.release(lock_name, holder_id)


async def _update_job_status(job_name: str, status: str) -> None:
    async with get_async_session() as session:
        stmt = select(ScheduledJob).where(ScheduledJob.name == job_name)
        job = (await session.execute(stmt)).scalar_one_or_none()
        if job is None:
            return

        job.last_run_at = datetime.utcnow()
        job.last_status = status


def _coerce_portals(portals_json: object | None) -> list[str]:
    if portals_json is None:
        return []

    if isinstance(portals_json, list):
        return [str(item).strip() for item in portals_json if str(item).strip()]

    if isinstance(portals_json, str):
        return [part.strip() for part in portals_json.split(",") if part.strip()]

    if isinstance(portals_json, dict):
        maybe = portals_json.get("portals")
        if isinstance(maybe, list):
            return [str(item).strip() for item in maybe if str(item).strip()]

    return []


class SchedulerService:
    """APScheduler v4 integration for ProcureWatch."""

    def __init__(self, db_url: str = "sqlite+aiosqlite:///data/schedules.db") -> None:
        self.db_url = db_url
        self._scheduler: AsyncScheduler | None = None
        self._holder_id = f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"

    async def start(self) -> None:
        """Start scheduler in foreground mode (blocking)."""
        engine = create_async_engine(self.db_url)
        data_store = SQLAlchemyDataStore(engine)

        async with AsyncScheduler(data_store) as scheduler:
            self._scheduler = scheduler
            await self._sync_schedules_from_db()
            await scheduler.run_until_stopped()

    async def _sync_schedules_from_db(self) -> None:
        """Read ScheduledJob table and add to APScheduler."""
        if self._scheduler is None:
            raise RuntimeError("Scheduler is not initialized")

        async with get_async_session() as session:
            stmt = select(ScheduledJob).where(ScheduledJob.enabled.is_(True))
            jobs = (await session.execute(stmt)).scalars().all()

        for job in jobs:
            trigger = self._build_trigger(job)
            max_jitter = None
            if job.jitter_minutes > 0:
                max_jitter = timedelta(minutes=job.jitter_minutes)

            await self._scheduler.add_schedule(
                execute_scheduled_job,
                trigger,
                id=job.name,
                args=[job.name, self._holder_id],
                conflict_policy=ConflictPolicy.replace,
                max_jitter=max_jitter,
            )

    async def trigger_now(self, job_name: str) -> None:
        """Trigger a scheduled job to run immediately."""
        engine = create_async_engine(self.db_url)
        data_store = SQLAlchemyDataStore(engine)

        async with AsyncScheduler(data_store) as scheduler:
            run_id = f"run-now:{job_name}:{uuid4().hex[:8]}"
            trigger = DateTrigger()

            async def _run_once(name: str) -> None:
                await execute_scheduled_job(name, self._holder_id)
                await scheduler.stop()

            await scheduler.add_schedule(
                _run_once,
                trigger,
                id=run_id,
                args=[job_name],
                conflict_policy=ConflictPolicy.replace,
            )

            await scheduler.run_until_stopped()

    def _build_trigger(self, job: ScheduledJob) -> CronTrigger | IntervalTrigger:
        """Convert ScheduledJob config to APScheduler trigger."""
        schedule_type = job.schedule_type.lower()
        timezone = job.timezone

        if schedule_type in {"daily", "weekday"}:
            hour, minute = _parse_time_of_day(job.time_of_day)
            day_of_week = "mon-fri" if schedule_type == "weekday" else None
            return CronTrigger(hour=hour, minute=minute, day_of_week=day_of_week, timezone=timezone)

        if schedule_type == "hourly":
            return IntervalTrigger(hours=1)

        if schedule_type == "cron":
            if not job.cron_expression:
                raise ValueError(f"Missing cron expression for job {job.name}")
            return CronTrigger.from_crontab(job.cron_expression, timezone=timezone)

        raise ValueError(f"Unsupported schedule type: {job.schedule_type}")


def _parse_time_of_day(time_of_day: str | None) -> tuple[int, int]:
    if not time_of_day:
        raise ValueError("time_of_day is required for daily/weekday schedules")

    parts = time_of_day.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_of_day}")

    hour = int(parts[0])
    minute = int(parts[1])

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Invalid time value: {time_of_day}")

    return hour, minute
