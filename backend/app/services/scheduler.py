import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import JobExecution, MonitoringTarget, ScheduledJob
from app.services.monitoring import execute_target_probe

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
JobHandler = Callable[[Session, ScheduledJob], Awaitable[object]]


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
        self.job_handlers: dict[str, JobHandler] = {}
        self._manual_run_ids: set[int] = set()

        self.register_handler(
            "connectivity_probe",
            self._execute_connectivity_probe,
        )

    def register_handler(
        self,
        job_type: str,
        handler: JobHandler,
    ) -> None:
        """Register the async executor for a scheduled job type."""
        normalized_type = job_type.strip() if isinstance(job_type, str) else ""

        if not normalized_type:
            raise ValueError("Job type must not be empty")

        if not callable(handler):
            raise ValueError("Job handler must be callable")

        if normalized_type in self.job_handlers:
            raise ValueError(
                f"A handler is already registered for job type "
                f"{normalized_type!r}"
            )

        self.job_handlers[normalized_type] = handler

    @staticmethod
    def _schedule_datetime(value: datetime | None) -> datetime | None:
        """Interpret stored naive datetimes as UTC for scheduler triggers."""
        if value is None:
            return None

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    @classmethod
    def build_trigger(
        cls,
        job: ScheduledJob,
    ) -> IntervalTrigger | CronTrigger:
        """Build an APScheduler trigger from a persisted schedule definition."""
        timezone_name = (job.timezone or "UTC").strip()

        try:
            job_timezone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"Unknown schedule timezone: {timezone_name!r}"
            ) from exc

        start_date = cls._schedule_datetime(job.start_at)
        end_date = cls._schedule_datetime(job.end_at)

        if start_date is not None and end_date is not None:
            if end_date <= start_date:
                raise ValueError("Schedule end_at must be later than start_at")

        if job.schedule_type == "interval":
            if job.interval_seconds is None or job.interval_seconds < 1:
                raise ValueError(
                    "Interval schedules require interval_seconds of at least 1"
                )

            return IntervalTrigger(
                seconds=job.interval_seconds,
                timezone=job_timezone,
                start_date=start_date,
                end_date=end_date,
            )

        if job.schedule_type == "cron":
            expression = (job.cron_expression or "").strip()
            fields = expression.split()

            if len(fields) != 5:
                raise ValueError(
                    "Cron expressions must contain exactly five fields "
                    "(minute hour day month day_of_week)"
                )

            return CronTrigger(
                minute=fields[0],
                hour=fields[1],
                day=fields[2],
                month=fields[3],
                day_of_week=fields[4],
                timezone=job_timezone,
                start_date=start_date,
                end_date=end_date,
            )

        raise ValueError(
            f"Unsupported schedule type: {job.schedule_type!r}"
        )

    @staticmethod
    def _trigger_signature(trigger: IntervalTrigger | CronTrigger) -> tuple:
        """Return stable trigger configuration for reconciliation."""
        if isinstance(trigger, IntervalTrigger):
            return (
                "interval",
                trigger.interval,
                str(trigger.timezone),
                trigger.start_date,
                trigger.end_date,
            )

        return (
            "cron",
            tuple((field.name, str(field)) for field in trigger.fields),
            str(trigger.timezone),
            trigger.start_date,
            trigger.end_date,
        )

    def queue_run_now(self, scheduled_job_id: int) -> bool:
        """Queue one immediate manual execution without changing its schedule."""
        if not self.scheduler.running:
            raise RuntimeError("Scheduler is not running")

        if scheduled_job_id in self._manual_run_ids:
            return False

        self._manual_run_ids.add(scheduled_job_id)
        try:
            self.scheduler.add_job(
                self._run_manual_job,
                trigger=DateTrigger(run_date=datetime.now(timezone.utc)),
                id=f"manual-{scheduled_job_id}",
                args=[scheduled_job_id],
                name=f"Manual run for job {scheduled_job_id}",
                max_instances=1,
                # Manual requests should not be silently discarded if the
                # event loop is temporarily delayed.
                misfire_grace_time=None,
            )
        except Exception:
            self._manual_run_ids.discard(scheduled_job_id)
            raise

        return True

    async def _run_manual_job(self, scheduled_job_id: int) -> None:
        """Run a queued manual execution and release its duplicate guard."""
        try:
            await self._run_job(
                scheduled_job_id,
                execution_kind="manual",
            )
        finally:
            self._manual_run_ids.discard(scheduled_job_id)

    async def _execute_connectivity_probe(
        self,
        db: Session,
        job: ScheduledJob,
    ) -> object:
        if job.target_id is None:
            raise LookupError(
                f"Connectivity job {job.id} has no monitoring target"
            )

        return await execute_target_probe(db, job.target_id)

    async def _run_job(
        self,
        scheduled_job_id: int,
        execution_kind: str = "scheduled",
    ) -> None:
        """Execute any persisted job using its registered handler."""
        async with self.execution_lock:
            await self._run_job_locked(scheduled_job_id, execution_kind)

    async def _run_job_locked(
        self,
        scheduled_job_id: int,
        execution_kind: str = "scheduled",
    ) -> None:
        """Load and execute a persisted job using its registered handler."""
        db = self.session_factory()

        try:
            job = db.get(ScheduledJob, scheduled_job_id)

            if job is None:
                logger.warning(
                    "Cannot execute scheduled job %s: job not found",
                    scheduled_job_id,
                )
                return

            await self._execute_job(db, job, execution_kind)

        finally:
            db.close()

    async def _execute_job(
        self,
        db: Session,
        job: ScheduledJob,
        execution_kind: str = "scheduled",
    ) -> None:
        """Execute a loaded job and persist its execution outcome."""
        execution_id: int | None = None

        if not job.is_enabled:
            logger.info(
                "Scheduled job %s is disabled; execution skipped",
                job.id,
            )
            return

        if job.job_type == "connectivity_probe" and job.target_id is not None:
            target = db.get(MonitoringTarget, job.target_id)
            if target is None or not target.is_enabled:
                logger.info(
                    "Connectivity job %s has a disabled or missing target; "
                    "execution skipped",
                    job.id,
                )
                return

        if execution_kind == "scheduled" and job.is_paused:
            logger.info(
                "Scheduled job %s is paused; scheduled execution ignored",
                job.id,
            )
            return

        if execution_kind == "scheduled" and job.skip_next_run:
            skipped_at = utc_now()
            db.add(
                JobExecution(
                    job_id=job.id,
                    job_name=job.name,
                    started_at=skipped_at,
                    finished_at=skipped_at,
                    status="skipped",
                    error="Skipped by the skip-next control",
                )
            )
            job.skip_next_run = False
            db.commit()
            logger.info("Skipped next scheduled execution for job %s", job.id)
            return

        try:
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

            handler = self.job_handlers.get(job.job_type)

            if handler is None:
                raise RuntimeError(
                    f"No handler registered for job type {job.job_type!r}"
                )

            await handler(db, job)

            self._finish_execution(db, execution_id, status="success")

            logger.info(
                "Scheduled job %s (%s) completed successfully "
                "(execution %s)",
                job.id,
                job.job_type,
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

            logger.info("Scheduled job %s was skipped: %s", job.id, exc)

        except PermissionError as exc:
            if execution_id is not None:
                self._finish_execution(
                    db,
                    execution_id,
                    status="skipped",
                    error=str(exc),
                )

            logger.info("Scheduled job %s was skipped: %s", job.id, exc)

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

            logger.exception("Scheduled job %s failed", job.id)

    async def _run_target(
        self,
        target_id: int,
        scheduled_job_id: int | None = None,
    ) -> None:
        """Compatibility wrapper for existing target-based callers."""
        async with self.execution_lock:
            await self._run_target_locked(target_id, scheduled_job_id)

    async def _run_target_locked(
        self,
        target_id: int,
        scheduled_job_id: int | None = None,
    ) -> None:
        """Compatibility path for existing target-based callers."""
        db = self.session_factory()

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
                    "Cannot record execution for target %s: "
                    "scheduled job not found",
                    target_id,
                )
                return

            await self._execute_job(db, job)

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
        """Synchronize persistent connectivity jobs with APScheduler."""
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

                    # Uncustomized jobs retain the legacy behaviour of
                    # inheriting their interval and enabled state from
                    # the associated monitoring target.
                    if not job.schedule_is_customized:
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
                job.target_id: (
                    job.id,
                    self.build_trigger(job),
                    (
                        not job.schedule_is_customized
                        and job.schedule_type == "interval"
                    ),
                )
                for job in persistent_jobs
                if (
                    job.target_id in targets_by_id
                    and job.is_enabled
                    and not job.is_paused
                    and targets_by_id[job.target_id].is_enabled
                )
            }

        existing_jobs = {
            job.id: job
            for job in self.scheduler.get_jobs()
        }

        for job_id in existing_jobs:
            if not job_id.startswith("target-"):
                continue
            target_id = int(job_id.removeprefix("target-"))

            if target_id not in desired_jobs:
                self.scheduler.remove_job(job_id)

        for target_id, (
            persistent_job_id,
            trigger,
            run_immediately,
        ) in desired_jobs.items():
            job_id = f"target-{target_id}"
            existing_job = self.scheduler.get_job(job_id)

            if existing_job is not None:
                if (
                    self._trigger_signature(existing_job.trigger)
                    == self._trigger_signature(trigger)
                    and existing_job.args == [persistent_job_id, "scheduled"]
                ):
                    continue

                self.scheduler.remove_job(job_id)

            self.scheduler.add_job(
                self._run_job,
                trigger=trigger,
                id=job_id,
                args=[persistent_job_id, "scheduled"],
                name=f"Probe target {target_id}",
                # Preserve the legacy immediate first probe only for
                # inherited interval jobs. Custom intervals and cron jobs
                # must honour their trigger's calculated next fire time.
                next_run_time=(
                    utc_now()
                    if run_immediately
                    else trigger.get_next_fire_time(
                        None,
                        datetime.now(trigger.timezone),
                    )
                ),
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
        self._manual_run_ids.clear()
        logger.info("Monitoring scheduler stopped")


monitoring_scheduler = MonitoringScheduler()
