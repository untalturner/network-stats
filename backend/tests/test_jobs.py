import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.dependencies import get_db
from app.database import Base
from app.main import app
from app.services.scheduler import monitoring_scheduler


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(monitoring_scheduler, "start", lambda: None)
    monkeypatch.setattr(monitoring_scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(monitoring_scheduler, "reconcile", lambda: None)

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

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def create_job(client):
    from app.models import MonitoringTarget, ScheduledJob

    target_response = client.post(
        "/api/v1/targets",
        json={
            "name": "Cloudflare DNS",
            "target": "1.1.1.1",
            "protocol": "icmp",
            "interval_seconds": 30,
        },
    )
    assert target_response.status_code == 201

    target_id = target_response.json()["id"]

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())

    try:
        target = db.get(MonitoringTarget, target_id)
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
        return job.id, target_id
    finally:
        db.close()


def add_execution(client, job_id, status="success", error=None):
    from app.models import JobExecution, ScheduledJob

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())

    try:
        job = db.get(ScheduledJob, job_id)
        execution = JobExecution(
            job_id=job.id,
            job_name=job.name,
            status=status,
            error=error,
        )
        db.add(execution)
        db.commit()
    finally:
        db.close()


def test_list_jobs_includes_latest_execution(client):
    job_id, _ = create_job(client)
    add_execution(client, job_id, status="success")

    response = client.get("/api/v1/jobs")

    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id
    assert jobs[0]["name"] == "Probe target: Cloudflare DNS"
    assert jobs[0]["latest_execution"]["status"] == "success"


def test_list_job_executions(client):
    job_id, _ = create_job(client)
    add_execution(client, job_id, status="success")
    add_execution(client, job_id, status="failed", error="Probe failed")

    response = client.get(f"/api/v1/jobs/{job_id}/executions")

    assert response.status_code == 200
    executions = response.json()
    assert len(executions) == 2
    assert {item["status"] for item in executions} == {"success", "failed"}


def test_job_execution_history_survives_target_deletion(client):
    job_id, target_id = create_job(client)
    add_execution(client, job_id)

    delete_response = client.delete(f"/api/v1/targets/{target_id}")
    assert delete_response.status_code == 204

    response = client.get(f"/api/v1/jobs/{job_id}/executions")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["status"] == "success"


def test_job_execution_history_rejects_invalid_limit(client):
    job_id, _ = create_job(client)

    response = client.get(
        f"/api/v1/jobs/{job_id}/executions?limit=0"
    )

    assert response.status_code == 422


def test_job_execution_history_returns_404_for_missing_job(client):
    response = client.get("/api/v1/jobs/999/executions")

    assert response.status_code == 404


def test_scheduler_status(client):
    response = client.get("/api/v1/scheduler/status")

    assert response.status_code == 200
    result = response.json()
    assert result["is_running"] is False
    assert result["active_jobs"] == 0
    assert result["jobs"] == []


def test_update_job_schedule_marks_schedule_customized(client):
    from app.models import MonitoringTarget, ScheduledJob

    job_id, target_id = create_job(client)

    response = client.patch(
        f"/api/v1/jobs/{job_id}/schedule",
        json={
            "schedule_type": "interval",
            "interval_seconds": 300,
            "timezone": "Europe/Madrid",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["schedule_is_customized"] is True
    assert data["schedule_type"] == "interval"
    assert data["interval_seconds"] == 300
    assert data["timezone"] == "Europe/Madrid"

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())
    try:
        job = db.get(ScheduledJob, job_id)
        target = db.get(MonitoringTarget, target_id)
        assert job.schedule_is_customized is True
        assert job.interval_seconds == 300
        assert target.interval_seconds == 30
    finally:
        db.close()


def test_update_job_schedule_accepts_cron(client):
    job_id, _ = create_job(client)

    response = client.patch(
        f"/api/v1/jobs/{job_id}/schedule",
        json={
            "schedule_type": "cron",
            "cron_expression": "0 9 * * mon-fri",
            "timezone": "Europe/Madrid",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["schedule_type"] == "cron"
    assert data["cron_expression"] == "0 9 * * mon-fri"
    assert data["interval_seconds"] is None
    assert data["schedule_is_customized"] is True


def test_update_job_schedule_rejects_invalid_timezone_without_saving(client):
    from app.models import ScheduledJob

    job_id, _ = create_job(client)

    response = client.patch(
        f"/api/v1/jobs/{job_id}/schedule",
        json={
            "schedule_type": "interval",
            "interval_seconds": 300,
            "timezone": "Not/A_Real_Timezone",
        },
    )

    assert response.status_code == 422

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())
    try:
        job = db.get(ScheduledJob, job_id)
        assert job.schedule_is_customized is False
        assert job.interval_seconds == 30
        assert job.timezone == "UTC"
    finally:
        db.close()


def test_update_job_schedule_rejects_invalid_cron_without_saving(client):
    from app.models import ScheduledJob

    job_id, _ = create_job(client)

    response = client.patch(
        f"/api/v1/jobs/{job_id}/schedule",
        json={
            "schedule_type": "cron",
            "cron_expression": "not a valid cron",
            "timezone": "UTC",
        },
    )

    assert response.status_code == 422

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())
    try:
        job = db.get(ScheduledJob, job_id)
        assert job.schedule_is_customized is False
        assert job.schedule_type == "interval"
        assert job.interval_seconds == 30
    finally:
        db.close()


def test_update_job_schedule_returns_404_for_missing_job(client):
    response = client.patch(
        "/api/v1/jobs/999/schedule",
        json={
            "schedule_type": "interval",
            "interval_seconds": 300,
            "timezone": "UTC",
        },
    )

    assert response.status_code == 404
