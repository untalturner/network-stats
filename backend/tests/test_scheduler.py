from datetime import datetime
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
