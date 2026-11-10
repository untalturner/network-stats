from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.database import Base
from app.probes import ProbeResult
from app.services.scheduler import MonitoringScheduler


@pytest.fixture
def scheduler():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    testing_session_local = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    Base.metadata.create_all(bind=test_engine)

    instance = MonitoringScheduler(
        session_factory=testing_session_local,
    )

    yield instance

    instance.shutdown()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def create_target(session_factory, name, enabled=True, interval=30):
    with session_factory() as db:
        target = models.MonitoringTarget(
            name=name,
            target="1.1.1.1",
            protocol="icmp",
            interval_seconds=interval,
            timeout_seconds=5,
            is_enabled=enabled,
        )
        db.add(target)
        db.commit()
        db.refresh(target)
        return target.id


def test_reconcile_schedules_enabled_targets(scheduler):
    target_id = create_target(scheduler.session_factory, "Enabled target")
    create_target(
        scheduler.session_factory,
        "Disabled target",
        enabled=False,
    )

    scheduler.reconcile()

    jobs = scheduler.scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == f"target-{target_id}"
    assert jobs[0].trigger.interval.total_seconds() == 30
    assert jobs[0].max_instances == 1


def test_reconcile_updates_changed_interval(scheduler):
    target_id = create_target(scheduler.session_factory, "Target")

    scheduler.reconcile()

    with scheduler.session_factory() as db:
        target = db.get(models.MonitoringTarget, target_id)
        target.interval_seconds = 60
        db.commit()

    scheduler.reconcile()

    job = scheduler.scheduler.get_job(f"target-{target_id}")

    assert job is not None
    assert job.trigger.interval.total_seconds() == 60


def test_reconcile_removes_disabled_and_deleted_targets(scheduler):
    target_id = create_target(scheduler.session_factory, "Target")

    scheduler.reconcile()
    assert scheduler.scheduler.get_job(f"target-{target_id}") is not None

    with scheduler.session_factory() as db:
        target = db.get(models.MonitoringTarget, target_id)
        target.is_enabled = False
        db.commit()

    scheduler.reconcile()
    assert scheduler.scheduler.get_job(f"target-{target_id}") is None

    with scheduler.session_factory() as db:
        target = models.MonitoringTarget(
            name="Temporary target",
            target="1.1.1.1",
            protocol="icmp",
            interval_seconds=30,
            timeout_seconds=5,
            is_enabled=True,
        )
        db.add(target)
        db.commit()
        deleted_id = target.id

    scheduler.reconcile()
    assert scheduler.scheduler.get_job(f"target-{deleted_id}") is not None

    with scheduler.session_factory() as db:
        db.delete(db.get(models.MonitoringTarget, deleted_id))
        db.commit()

    scheduler.reconcile()
    assert scheduler.scheduler.get_job(f"target-{deleted_id}") is None


@pytest.mark.asyncio
async def test_run_target_persists_measurement(scheduler):
    target_id = create_target(scheduler.session_factory, "Target")

    result = ProbeResult(
        target="1.1.1.1",
        protocol="icmp",
        is_available=True,
        latency_ms=12.5,
        packet_loss_percent=0.0,
        measured_at=datetime(2026, 11, 5, 20, 0, 0),
        error=None,
    )

    from unittest.mock import patch

    with patch(
        "app.services.monitoring.probe_target",
        new_callable=AsyncMock,
        return_value=result,
    ) as mock_probe:
        await scheduler._run_target(target_id)

    mock_probe.assert_awaited_once_with(
        target="1.1.1.1",
        protocol="icmp",
        timeout_seconds=5.0,
    )

    with scheduler.session_factory() as db:
        measurements = db.query(models.Measurement).filter_by(
            target_id=target_id
        ).all()

    assert len(measurements) == 1
    assert measurements[0].is_available is True
    assert measurements[0].latency_ms == 12.5
    assert measurements[0].packet_loss_percent == 0.0
    assert measurements[0].error is None


@pytest.mark.asyncio
async def test_run_target_closes_database_session(scheduler):
    target_id = create_target(scheduler.session_factory, "Target")
    session = scheduler.session_factory()

    from unittest.mock import Mock, patch

    close_session = Mock(wraps=session.close)
    session.close = close_session
    scheduler.session_factory = lambda: session

    with patch(
        "app.services.scheduler.execute_target_probe",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Probe failed"),
    ):
        await scheduler._run_target(target_id)

    close_session.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_runs_probes_automatically(scheduler):
    import asyncio
    from unittest.mock import patch

    target_id = create_target(
        scheduler.session_factory,
        "Automatic scheduler target",
        interval=1,
    )

    result = ProbeResult(
        target="1.1.1.1",
        protocol="icmp",
        is_available=True,
        latency_ms=15.2,
        packet_loss_percent=0.0,
        measured_at=datetime(2026, 11, 5, 20, 0, 0),
        error=None,
    )

    with patch(
        "app.services.monitoring.probe_target",
        new_callable=AsyncMock,
        return_value=result,
    ) as mock_probe:
        scheduler.start()

        try:
            await asyncio.sleep(2.5)
        finally:
            scheduler.shutdown()

    assert mock_probe.await_count >= 2

    with scheduler.session_factory() as db:
        measurements = db.query(models.Measurement).filter_by(
            target_id=target_id
        ).all()

    assert len(measurements) >= 2
    assert all(measurement.is_available for measurement in measurements)
    assert all(measurement.latency_ms == 15.2 for measurement in measurements)


def test_build_interval_trigger_uses_timezone_and_date_bounds(scheduler):
    from zoneinfo import ZoneInfo

    job = models.ScheduledJob(
        name="Bounded interval",
        job_type="example",
        interval_seconds=60,
        schedule_type="interval",
        timezone="Europe/Madrid",
        start_at=datetime(2026, 11, 10, 8, 0, 0),
        end_at=datetime(2026, 11, 11, 8, 0, 0),
    )

    trigger = scheduler.build_trigger(job)

    assert trigger.interval.total_seconds() == 60
    assert trigger.timezone == ZoneInfo("Europe/Madrid")
    assert trigger.start_date.astimezone(timezone.utc) == datetime(
        2026, 11, 10, 8, 0, 0, tzinfo=timezone.utc
    )
    assert trigger.end_date.astimezone(timezone.utc) == datetime(
        2026, 11, 11, 8, 0, 0, tzinfo=timezone.utc
    )


def test_build_cron_trigger_supports_weekdays_and_timezone(scheduler):
    from zoneinfo import ZoneInfo

    job = models.ScheduledJob(
        name="Weekday morning task",
        job_type="example",
        schedule_type="cron",
        cron_expression="0 9 * * mon-fri",
        timezone="Europe/Madrid",
    )

    trigger = scheduler.build_trigger(job)

    assert trigger.timezone == ZoneInfo("Europe/Madrid")
    assert any(
        field.name == "day_of_week" and str(field) == "mon-fri"
        for field in trigger.fields
    )

    now = datetime(
        2026, 11, 10, 8, 0, 0,
        tzinfo=ZoneInfo("Europe/Madrid"),
    )
    next_run = trigger.get_next_fire_time(None, now)

    assert next_run is not None
    assert next_run.hour == 9
    assert next_run.minute == 0


def test_build_cron_trigger_rejects_invalid_field_count(scheduler):
    job = models.ScheduledJob(
        name="Invalid cron",
        job_type="example",
        schedule_type="cron",
        cron_expression="0 9 * *",
        timezone="UTC",
    )

    with pytest.raises(ValueError, match="exactly five fields"):
        scheduler.build_trigger(job)


def test_build_trigger_rejects_unknown_timezone(scheduler):
    job = models.ScheduledJob(
        name="Invalid timezone",
        job_type="example",
        interval_seconds=60,
        schedule_type="interval",
        timezone="Not/A_Real_Timezone",
    )

    with pytest.raises(ValueError, match="Unknown schedule timezone"):
        scheduler.build_trigger(job)


def test_build_trigger_rejects_invalid_date_range(scheduler):
    job = models.ScheduledJob(
        name="Invalid date range",
        job_type="example",
        interval_seconds=60,
        schedule_type="interval",
        timezone="UTC",
        start_at=datetime(2026, 11, 11, 8, 0, 0),
        end_at=datetime(2026, 11, 10, 8, 0, 0),
    )

    with pytest.raises(ValueError, match="later than start_at"):
        scheduler.build_trigger(job)


def test_reconcile_preserves_custom_interval_when_target_changes(scheduler):
    target_id = create_target(scheduler.session_factory, "Custom schedule target")
    scheduler.reconcile()

    with scheduler.session_factory() as db:
        target = db.get(models.MonitoringTarget, target_id)
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        job.schedule_is_customized = True
        job.interval_seconds = 300
        target.interval_seconds = 60
        db.commit()

    scheduler.reconcile()

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        assert job.schedule_is_customized is True
        assert job.interval_seconds == 300

    runtime_job = scheduler.scheduler.get_job(f"target-{target_id}")
    assert runtime_job is not None
    assert runtime_job.trigger.interval.total_seconds() == 300


def test_reconcile_preserves_custom_job_enabled_state(scheduler):
    target_id = create_target(scheduler.session_factory, "Custom enabled target")
    scheduler.reconcile()

    with scheduler.session_factory() as db:
        target = db.get(models.MonitoringTarget, target_id)
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        job.schedule_is_customized = True
        job.is_enabled = False
        target.interval_seconds = 120
        db.commit()

    scheduler.reconcile()

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        assert job.schedule_is_customized is True
        assert job.is_enabled is False
        assert job.interval_seconds == 30

    assert scheduler.scheduler.get_job(f"target-{target_id}") is None


def test_disabled_target_blocks_custom_schedule_without_overwriting_it(scheduler):
    target_id = create_target(scheduler.session_factory, "Custom target gate")
    scheduler.reconcile()

    with scheduler.session_factory() as db:
        target = db.get(models.MonitoringTarget, target_id)
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        job.schedule_is_customized = True
        job.interval_seconds = 300
        target.is_enabled = False
        db.commit()

    scheduler.reconcile()

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        assert job.schedule_is_customized is True
        assert job.is_enabled is True
        assert job.interval_seconds == 300

    assert scheduler.scheduler.get_job(f"target-{target_id}") is None

    with scheduler.session_factory() as db:
        target = db.get(models.MonitoringTarget, target_id)
        target.is_enabled = True
        db.commit()

    scheduler.reconcile()
    runtime_job = scheduler.scheduler.get_job(f"target-{target_id}")
    assert runtime_job is not None
    assert runtime_job.trigger.interval.total_seconds() == 300


def test_custom_interval_respects_future_start_date(scheduler):
    from datetime import timedelta, timezone

    target_id = create_target(
        scheduler.session_factory,
        "Future custom interval",
    )
    scheduler.reconcile()

    start_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(
            target_id=target_id
        ).one()
        job.schedule_is_customized = True
        job.interval_seconds = 300
        job.start_at = start_at
        db.commit()

    scheduler.reconcile()

    runtime_job = scheduler.scheduler.get_job(f"target-{target_id}")
    assert runtime_job is not None
    assert runtime_job.next_run_time is not None
    assert runtime_job.next_run_time.astimezone(timezone.utc) >= start_at.replace(
        tzinfo=timezone.utc
    )


def test_custom_cron_uses_next_cron_fire_time(scheduler):
    from zoneinfo import ZoneInfo

    target_id = create_target(
        scheduler.session_factory,
        "Custom cron schedule",
    )
    scheduler.reconcile()

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(
            target_id=target_id
        ).one()
        job.schedule_is_customized = True
        job.schedule_type = "cron"
        job.interval_seconds = None
        job.cron_expression = "0 9 * * mon-fri"
        job.timezone = "Europe/Madrid"
        db.commit()

    scheduler.reconcile()

    runtime_job = scheduler.scheduler.get_job(f"target-{target_id}")
    assert runtime_job is not None
    assert runtime_job.next_run_time is not None

    local_next_run = runtime_job.next_run_time.astimezone(
        ZoneInfo("Europe/Madrid")
    )
    assert local_next_run.hour == 9
    assert local_next_run.minute == 0
    assert local_next_run.weekday() < 5


def test_inherited_interval_keeps_immediate_first_probe(scheduler):
    target_id = create_target(
        scheduler.session_factory,
        "Inherited immediate interval",
    )

    before_reconcile = datetime.now(timezone.utc)
    scheduler.reconcile()

    runtime_job = scheduler.scheduler.get_job(f"target-{target_id}")
    assert runtime_job is not None
    assert runtime_job.next_run_time is not None
    assert runtime_job.next_run_time.astimezone(timezone.utc) <= (
        before_reconcile + timedelta(seconds=2)
    )


@pytest.mark.asyncio
async def test_scheduled_run_consumes_skip_next_without_calling_handler(scheduler):
    handler = AsyncMock()
    scheduler.register_handler("skip_test", handler)

    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Skip test",
            job_type="skip_test",
            schedule_type="interval",
            interval_seconds=60,
            skip_next_run=True,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    await scheduler._run_job(job_id, execution_kind="scheduled")

    handler.assert_not_awaited()
    with scheduler.session_factory() as db:
        job = db.get(models.ScheduledJob, job_id)
        execution = (
            db.query(models.JobExecution)
            .filter_by(job_id=job_id)
            .one()
        )
        assert job.skip_next_run is False
        assert execution.status == "skipped"
        assert execution.finished_at is not None
        assert "skip-next" in execution.error.lower()


@pytest.mark.asyncio
async def test_manual_run_does_not_consume_skip_next(scheduler):
    handler = AsyncMock()
    scheduler.register_handler("manual_test", handler)

    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Manual test",
            job_type="manual_test",
            schedule_type="interval",
            interval_seconds=60,
            skip_next_run=True,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    await scheduler._run_job(job_id, execution_kind="manual")

    handler.assert_awaited_once()
    with scheduler.session_factory() as db:
        job = db.get(models.ScheduledJob, job_id)
        execution = (
            db.query(models.JobExecution)
            .filter_by(job_id=job_id)
            .one()
        )
        assert job.skip_next_run is True
        assert execution.status == "success"


@pytest.mark.asyncio
async def test_queue_run_now_rejects_duplicate_manual_request(scheduler):
    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Queue test",
            job_type="queue_test",
            schedule_type="interval",
            interval_seconds=60,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    scheduler.scheduler.start()
    try:
        assert scheduler.queue_run_now(job_id) is True
        assert scheduler.queue_run_now(job_id) is False
        assert scheduler.scheduler.get_job(f"manual-{job_id}") is not None
    finally:
        scheduler.shutdown()


def test_queue_run_now_requires_running_scheduler(scheduler):
    with pytest.raises(RuntimeError, match="Scheduler is not running"):
        scheduler.queue_run_now(123)



def test_reconcile_removes_paused_job_without_disabling_it(scheduler):
    target_id = create_target(scheduler.session_factory, "Pause target")
    scheduler.reconcile()

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        job.is_paused = True
        db.commit()

    scheduler.reconcile()

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        assert job.is_paused is True
        assert job.is_enabled is True

    assert scheduler.scheduler.get_job(f"target-{target_id}") is None


def test_reconcile_restores_paused_job_after_resume(scheduler):
    target_id = create_target(scheduler.session_factory, "Resume target")
    scheduler.reconcile()

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        job.is_paused = True
        db.commit()

    scheduler.reconcile()
    assert scheduler.scheduler.get_job(f"target-{target_id}") is None

    with scheduler.session_factory() as db:
        job = db.query(models.ScheduledJob).filter_by(target_id=target_id).one()
        job.is_paused = False
        db.commit()

    scheduler.reconcile()
    runtime_job = scheduler.scheduler.get_job(f"target-{target_id}")
    assert runtime_job is not None


@pytest.mark.asyncio
async def test_paused_job_ignores_scheduled_run(scheduler):
    handler = AsyncMock()
    scheduler.register_handler("paused_test", handler)

    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Paused test",
            job_type="paused_test",
            schedule_type="interval",
            interval_seconds=60,
            is_paused=True,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    await scheduler._run_job(job_id, execution_kind="scheduled")

    handler.assert_not_awaited()
    with scheduler.session_factory() as db:
        assert db.query(models.JobExecution).filter_by(job_id=job_id).count() == 0


@pytest.mark.asyncio
async def test_manual_run_is_allowed_while_job_is_paused(scheduler):
    handler = AsyncMock()
    scheduler.register_handler("paused_manual_test", handler)

    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Paused manual test",
            job_type="paused_manual_test",
            schedule_type="interval",
            interval_seconds=60,
            is_paused=True,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    await scheduler._run_job(job_id, execution_kind="manual")

    handler.assert_awaited_once()
    with scheduler.session_factory() as db:
        job = db.get(models.ScheduledJob, job_id)
        execution = db.query(models.JobExecution).filter_by(job_id=job_id).one()
        assert job.is_paused is True
        assert execution.status == "success"


@pytest.mark.asyncio
async def test_job_execution_timeout_cancels_handler_and_records_failure(scheduler):
    import asyncio

    cancelled = asyncio.Event()

    async def slow_handler(db, job):
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.set()

    scheduler.register_handler("timeout_test", slow_handler)

    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Timeout test",
            job_type="timeout_test",
            schedule_type="interval",
            interval_seconds=60,
            execution_timeout_seconds=0.05,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    await scheduler._run_job(job_id)

    assert cancelled.is_set()

    with scheduler.session_factory() as db:
        execution = (
            db.query(models.JobExecution)
            .filter_by(job_id=job_id)
            .one()
        )
        assert execution.status == "failed"
        assert execution.finished_at is not None
        assert "timed out after 0.05 seconds" in execution.error


def test_job_execution_timeout_defaults_to_five_minutes(scheduler):
    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Default timeout test",
            job_type="timeout_default_test",
            schedule_type="interval",
            interval_seconds=60,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        assert job.execution_timeout_seconds == 300.0


@pytest.mark.asyncio
async def test_job_retries_then_succeeds_and_records_attempt_history(scheduler):
    handler = AsyncMock(
        side_effect=[RuntimeError("temporary network failure"), None]
    )
    scheduler.register_handler("retry_success_test", handler)

    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Retry success test",
            job_type="retry_success_test",
            schedule_type="interval",
            interval_seconds=60,
            max_retries=1,
            retry_delay_seconds=0.01,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    await scheduler._run_job(job_id)

    assert handler.await_count == 2
    with scheduler.session_factory() as db:
        executions = db.query(models.JobExecution).filter_by(job_id=job_id).all()
        assert len(executions) == 1
        execution = executions[0]
        assert execution.status == "success"
        assert execution.attempt_count == 2
        assert len(execution.attempt_errors) == 1
        assert "temporary network failure" in execution.attempt_errors[0]
        assert execution.error is None


@pytest.mark.asyncio
async def test_job_fails_after_exhausting_retries(scheduler):
    handler = AsyncMock(side_effect=RuntimeError("persistent failure"))
    scheduler.register_handler("retry_failure_test", handler)

    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Retry failure test",
            job_type="retry_failure_test",
            schedule_type="interval",
            interval_seconds=60,
            max_retries=2,
            retry_delay_seconds=0.01,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    await scheduler._run_job(job_id)

    assert handler.await_count == 3
    with scheduler.session_factory() as db:
        execution = db.query(models.JobExecution).filter_by(job_id=job_id).one()
        assert execution.status == "failed"
        assert execution.attempt_count == 3
        assert len(execution.attempt_errors) == 3
        assert execution.error == "persistent failure"


@pytest.mark.asyncio
async def test_job_does_not_retry_intentional_skip(scheduler):
    handler = AsyncMock(side_effect=LookupError("resource unavailable"))
    scheduler.register_handler("retry_skip_test", handler)

    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Retry skip test",
            job_type="retry_skip_test",
            schedule_type="interval",
            interval_seconds=60,
            max_retries=3,
            retry_delay_seconds=0.01,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    await scheduler._run_job(job_id)

    handler.assert_awaited_once()
    with scheduler.session_factory() as db:
        execution = db.query(models.JobExecution).filter_by(job_id=job_id).one()
        assert execution.status == "skipped"
        assert execution.attempt_count == 1
        assert execution.attempt_errors == []


def test_job_retry_defaults_are_disabled(scheduler):
    with scheduler.session_factory() as db:
        job = models.ScheduledJob(
            name="Default retry test",
            job_type="retry_default_test",
            schedule_type="interval",
            interval_seconds=60,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        assert job.max_retries == 0
        assert job.retry_delay_seconds == 5.0
