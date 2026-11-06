import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import JobExecution, MonitoringTarget, ScheduledJob
from app.services.monitoring import execute_target_probe

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MonitoringScheduler:
    def __init__(
        self,
        session_factory: SessionFactory = SessionLocal,
    ):
        self.session_factory = session_factory
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.execution_lock = asyncio.Lock()

    async def _run_target(
        self,
        target_id: int,
        scheduled_job_id: int | None = None,
    ) -> None:
        async with self.execution_lock:
            await self._run_target_locked(target_id, scheduled_job_id)

    async def _run_target_locked(
        self,
        target_id: int,
        scheduled_job_id: int | None = None,
    ) -> None:
        db = self.session_factory()
        execution_id: int | None = None

        try:
            job = (
                db.get(ScheduledJob, scheduled_job_id)
                if scheduled_job_id is not None
                else db.scalar(
                    select(ScheduledJob).where(
                        ScheduledJob.target_id == target_id
                    )
                )
            )

            target = db.get(MonitoringTarget, target_id)

            if job is None and target is not None:
                job = ScheduledJob(
                    name=f"Probe target: {target.name}",
                    job_type="connectivity_probe",
                    interval_seconds=target.interval_seconds,
                    is_enabled=target.is_enabled,
                    target_id=target.id,
                )
                db.add(job)
                db.commit()
                db.refresh(job)

            if job is None:
                logger.warning(
                    "Cannot record execution for target %s: scheduled job not found",
                    target_id,
                )
                return

            execution = JobExecution(
                job_id=job.id,
                job_name=job.name,
                started_at=utc_now(),
                status="running",
            )
            db.add(execution)
            db.commit()
            db.refresh(execution)
            execution_id = execution.id

            await execute_target_probe(db, target_id)

            self._finish_execution(db, execution_id, status="success")

            logger.info(
                "Scheduled probe completed for target %s (execution %s)",
                target_id,
                execution_id,
            )

        except LookupError as exc:
            if execution_id is not None:
                self._finish_execution(
                    db,
                    execution_id,
                    status="skipped",
                    error=str(exc),
                )

            logger.info(
                "Scheduled probe skipped because target %s no longer exists",
                target_id,
            )

        except PermissionError as exc:
            if execution_id is not None:
                self._finish_execution(
                    db,
                    execution_id,
                    status="skipped",
                    error=str(exc),
                )

            logger.debug(
                "Scheduled probe skipped because target %s is disabled",
                target_id,
            )

        except Exception as exc:
            if execution_id is not None:
                try:
                    self._finish_execution(
                        db,
                        execution_id,
                        status="failed",
                        error=str(exc),
                    )
                except Exception:
                    logger.exception(
                        "Could not persist failure for execution %s",
                        execution_id,
                    )

            logger.exception(
                "Scheduled probe failed for target %s",
                target_id,
            )

        finally:
            db.close()

    @staticmethod
    def _finish_execution(
        db: Session,
        execution_id: int,
        status: str,
        error: str | None = None,
    ) -> None:
        execution = db.get(JobExecution, execution_id)

        if execution is None:
            raise LookupError(f"Execution {execution_id} not found")

        execution.status = status
        execution.finished_at = utc_now()
        execution.error = error[:2000] if error else None
        db.commit()

    def reconcile(self) -> None:
        """Synchronize persistent jobs and APScheduler jobs with targets."""
        with self.session_factory() as db:
            targets = db.scalars(select(MonitoringTarget)).all()
            targets_by_id = {target.id: target for target in targets}

            scheduled_jobs = db.scalars(
                select(ScheduledJob).where(
                    ScheduledJob.job_type == "connectivity_probe"
                )
            ).all()

            jobs_by_target = {
                job.target_id: job
                for job in scheduled_jobs
                if job.target_id is not None
            }

            for target in targets:
                job = jobs_by_target.get(target.id)

                if job is None:
                    job = ScheduledJob(
                        name=f"Probe target: {target.name}",
                        job_type="connectivity_probe",
                        interval_seconds=target.interval_seconds,
                        is_enabled=target.is_enabled,
                        target_id=target.id,
                    )
                    db.add(job)
                else:
                    job.name = f"Probe target: {target.name}"
                    job.interval_seconds = target.interval_seconds
                    job.is_enabled = target.is_enabled

            for job in scheduled_jobs:
                if job.target_id not in targets_by_id:
                    job.is_enabled = False

            db.commit()

            persistent_jobs = db.scalars(
                select(ScheduledJob).where(
                    ScheduledJob.job_type == "connectivity_probe"
                )
            ).all()

            desired_jobs = {
                job.target_id: (job.id, job.interval_seconds)
                for job in persistent_jobs
                if (
                    job.target_id in targets_by_id
                    and job.is_enabled
                    and targets_by_id[job.target_id].is_enabled
                )
            }

        existing_jobs = {
            job.id: job
            for job in self.scheduler.get_jobs()
        }

        for job_id in existing_jobs:
            target_id = int(job_id.removeprefix("target-"))

            if target_id not in desired_jobs:
                self.scheduler.remove_job(job_id)

        for target_id, (persistent_job_id, interval_seconds) in desired_jobs.items():
            job_id = f"target-{target_id}"
            existing_job = self.scheduler.get_job(job_id)

            if existing_job is not None:
                current_interval = existing_job.trigger.interval.total_seconds()

                if (
                    current_interval == interval_seconds
                    and existing_job.args == [target_id, persistent_job_id]
                ):
                    continue

                self.scheduler.remove_job(job_id)

            self.scheduler.add_job(
                self._run_target,
                trigger=IntervalTrigger(
                    seconds=interval_seconds,
                    timezone="UTC",
                ),
                id=job_id,
                args=[target_id, persistent_job_id],
                name=f"Probe target {target_id}",
                next_run_time=utc_now(),
                max_instances=1,
                coalesce=True,
                misfire_grace_time=30,
            )

        logger.info(
            "Monitoring scheduler reconciled: %s enabled targets",
            len(desired_jobs),
        )

    def start(self) -> None:
        if self.scheduler.running:
            return

        self.scheduler.start()
        self.reconcile()
        logger.info("Monitoring scheduler started")

    def shutdown(self) -> None:
        if not self.scheduler.running:
            return

        self.scheduler.shutdown(wait=False)
        logger.info("Monitoring scheduler stopped")


monitoring_scheduler = MonitoringScheduler()
