from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.database import Base
from app.models import JobExecution, ScheduledJob
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


def create_generic_job(session_factory, job_type="example_task", enabled=True):
    with session_factory() as db:
        job = ScheduledJob(
            name="Generic test job",
            job_type=job_type,
            is_enabled=enabled,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.id


def get_executions(session_factory, job_id):
    with session_factory() as db:
        return db.scalars(
            select(JobExecution)
            .where(JobExecution.job_id == job_id)
            .order_by(JobExecution.id)
        ).all()


@pytest.mark.asyncio
async def test_registered_handler_executes_generic_job(scheduler):
    job_id = create_generic_job(scheduler.session_factory)
    handled = []

    async def handler(db, job):
        handled.append((job.id, job.job_type))

    scheduler.register_handler("example_task", handler)

    await scheduler._run_job(job_id)

    assert handled == [(job_id, "example_task")]

    executions = get_executions(scheduler.session_factory, job_id)
    assert len(executions) == 1
    assert executions[0].status == "success"
    assert executions[0].finished_at is not None


@pytest.mark.asyncio
async def test_handler_failure_is_recorded(scheduler):
    job_id = create_generic_job(scheduler.session_factory)

    async def failing_handler(db, job):
        raise RuntimeError("Example handler failure")

    scheduler.register_handler("example_task", failing_handler)

    await scheduler._run_job(job_id)

    executions = get_executions(scheduler.session_factory, job_id)
    assert len(executions) == 1
    assert executions[0].status == "failed"
    assert "Example handler failure" in executions[0].error


@pytest.mark.asyncio
async def test_missing_handler_is_recorded_as_failure(scheduler):
    job_id = create_generic_job(
        scheduler.session_factory,
        job_type="unregistered_task",
    )

    await scheduler._run_job(job_id)

    executions = get_executions(scheduler.session_factory, job_id)
    assert len(executions) == 1
    assert executions[0].status == "failed"
    assert "No handler registered" in executions[0].error


@pytest.mark.asyncio
async def test_disabled_generic_job_is_not_executed(scheduler):
    job_id = create_generic_job(
        scheduler.session_factory,
        enabled=False,
    )
    handled = []

    async def handler(db, job):
        handled.append(job.id)

    scheduler.register_handler("example_task", handler)

    await scheduler._run_job(job_id)

    assert handled == []
    assert get_executions(scheduler.session_factory, job_id) == []


def test_duplicate_handler_registration_is_rejected(scheduler):
    async def handler(db, job):
        return None

    scheduler.register_handler("example_task", handler)

    with pytest.raises(ValueError, match="already registered"):
        scheduler.register_handler("example_task", handler)


def test_connectivity_handler_is_registered_by_default(scheduler):
    assert "connectivity_probe" in scheduler.job_handlers
