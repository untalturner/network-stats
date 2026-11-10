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
    assert all(item["attempt_count"] == 1 for item in executions)
    assert all(item["attempt_errors"] == [] for item in executions)


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
            "execution_timeout_seconds": 45,
            "max_retries": 2,
            "retry_delay_seconds": 4,
            "max_concurrent_runs": 3,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["schedule_is_customized"] is True
    assert data["schedule_type"] == "interval"
    assert data["interval_seconds"] == 300
    assert data["timezone"] == "Europe/Madrid"
    assert data["execution_timeout_seconds"] == 45
    assert data["max_retries"] == 2
    assert data["retry_delay_seconds"] == 4
    assert data["max_concurrent_runs"] == 3

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())
    try:
        job = db.get(ScheduledJob, job_id)
        target = db.get(MonitoringTarget, target_id)
        assert job.schedule_is_customized is True
        assert job.interval_seconds == 300
        assert job.execution_timeout_seconds == 45
        assert job.max_retries == 2
        assert job.retry_delay_seconds == 4
        assert job.max_concurrent_runs == 3
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


def test_skip_next_marks_job_and_is_idempotent(client):
    from app.models import ScheduledJob

    job_id, _ = create_job(client)

    first = client.post(f"/api/v1/jobs/{job_id}/skip-next")
    second = client.post(f"/api/v1/jobs/{job_id}/skip-next")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "already marked" in second.json()["message"]

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())
    try:
        job = db.get(ScheduledJob, job_id)
        assert job.skip_next_run is True
    finally:
        db.close()


def test_skip_next_returns_404_for_missing_job(client):
    response = client.post("/api/v1/jobs/999/skip-next")
    assert response.status_code == 404


def test_run_now_queues_enabled_job(client, monkeypatch):
    job_id, _ = create_job(client)
    calls = []

    def queue_run_now(scheduled_job_id):
        calls.append(scheduled_job_id)
        return True

    monkeypatch.setattr(
        monitoring_scheduler,
        "queue_run_now",
        queue_run_now,
    )

    response = client.post(f"/api/v1/jobs/{job_id}/run")

    assert response.status_code == 202
    assert response.json()["job_id"] == job_id
    assert calls == [job_id]


def test_run_now_rejects_disabled_target(client, monkeypatch):
    from app.models import MonitoringTarget

    job_id, target_id = create_job(client)

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())
    try:
        target = db.get(MonitoringTarget, target_id)
        target.is_enabled = False
        db.commit()
    finally:
        db.close()

    def unexpected_queue(_job_id):
        raise AssertionError("Disabled target must be rejected before queueing")

    monkeypatch.setattr(
        monitoring_scheduler,
        "queue_run_now",
        unexpected_queue,
    )

    response = client.post(f"/api/v1/jobs/{job_id}/run")
    assert response.status_code == 409


def test_run_now_returns_503_when_scheduler_is_stopped(client, monkeypatch):
    job_id, _ = create_job(client)

    def stopped_scheduler(_job_id):
        raise RuntimeError("Scheduler is not running")

    monkeypatch.setattr(
        monitoring_scheduler,
        "queue_run_now",
        stopped_scheduler,
    )

    response = client.post(f"/api/v1/jobs/{job_id}/run")
    assert response.status_code == 503



def test_pause_job_persists_paused_state_without_disabling(client):
    from app.models import ScheduledJob

    job_id, _ = create_job(client)

    first = client.post(f"/api/v1/jobs/{job_id}/pause")
    second = client.post(f"/api/v1/jobs/{job_id}/pause")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "already paused" in second.json()["message"]

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())
    try:
        job = db.get(ScheduledJob, job_id)
        assert job.is_paused is True
        assert job.is_enabled is True
    finally:
        db.close()


def test_resume_job_clears_paused_state(client):
    from app.models import ScheduledJob

    job_id, _ = create_job(client)
    pause_response = client.post(f"/api/v1/jobs/{job_id}/pause")
    assert pause_response.status_code == 200

    response = client.post(f"/api/v1/jobs/{job_id}/resume")
    assert response.status_code == 200
    assert response.json()["message"] == "Scheduled job resumed"

    dependency = app.dependency_overrides[get_db]
    db = next(dependency())
    try:
        job = db.get(ScheduledJob, job_id)
        assert job.is_paused is False
        assert job.is_enabled is True
    finally:
        db.close()


def test_pause_and_resume_return_404_for_missing_job(client):
    assert client.post("/api/v1/jobs/999/pause").status_code == 404
    assert client.post("/api/v1/jobs/999/resume").status_code == 404



def test_update_job_schedule_rejects_concurrency_above_global_limit(client):
    job_id, _ = create_job(client)

    response = client.patch(
        f"/api/v1/jobs/{job_id}/schedule",
        json={
            "schedule_type": "interval",
            "interval_seconds": 60,
            "timezone": "UTC",
            "max_concurrent_runs": 5,
        },
    )

    assert response.status_code == 422
