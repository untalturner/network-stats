from datetime import datetime
from unittest.mock import AsyncMock, patch

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
from app.probes import ProbeResult


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

    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
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


def create_target(client, is_enabled=True):
    response = client.post(
        "/api/v1/targets",
        json={
            "name": "Cloudflare DNS",
            "target": "1.1.1.1",
            "protocol": "icmp",
            "is_enabled": is_enabled,
        },
    )

    assert response.status_code == 201
    return response.json()["id"]


def test_run_probe_and_persist_measurement(client):
    target_id = create_target(client)

    probe_result = ProbeResult(
        target="1.1.1.1",
        protocol="icmp",
        is_available=True,
        latency_ms=22.5,
        packet_loss_percent=0.0,
        measured_at=datetime(2026, 11, 5, 19, 30, 0),
        error=None,
    )

    with patch(
        "app.services.monitoring.probe_target",
        new_callable=AsyncMock,
        return_value=probe_result,
    ) as mock_probe:
        response = client.post(f"/api/v1/targets/{target_id}/probe")

    assert response.status_code == 201

    measurement = response.json()
    assert measurement["target_id"] == target_id
    assert measurement["is_available"] is True
    assert measurement["latency_ms"] == 22.5
    assert measurement["packet_loss_percent"] == 0.0
    assert measurement["error"] is None

    mock_probe.assert_awaited_once_with(
        target="1.1.1.1",
        protocol="icmp",
        timeout_seconds=5.0,
    )

    history_response = client.get(
        f"/api/v1/targets/{target_id}/measurements"
    )

    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    assert history[0]["id"] == measurement["id"]


def test_probe_rejects_missing_target(client):
    response = client.post("/api/v1/targets/999/probe")

    assert response.status_code == 404


def test_probe_rejects_disabled_target(client):
    target_id = create_target(client, is_enabled=False)

    with patch(
        "app.services.monitoring.probe_target",
        new_callable=AsyncMock,
    ) as mock_probe:
        response = client.post(f"/api/v1/targets/{target_id}/probe")

    assert response.status_code == 409
    mock_probe.assert_not_awaited()


def test_measurement_history_rejects_missing_target(client):
    response = client.get("/api/v1/targets/999/measurements")

    assert response.status_code == 404


def test_measurement_history_validates_limit(client):
    target_id = create_target(client)

    too_small = client.get(
        f"/api/v1/targets/{target_id}/measurements?limit=0"
    )
    too_large = client.get(
        f"/api/v1/targets/{target_id}/measurements?limit=501"
    )

    assert too_small.status_code == 422
    assert too_large.status_code == 422
