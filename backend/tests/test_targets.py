import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.database import Base
from app.main import app
from app.services.scheduler import monitoring_scheduler
from app import models  # noqa: F401


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


def test_create_and_list_target(client):
    response = client.post(
        "/api/v1/targets",
        json={
            "name": "Cloudflare DNS",
            "target": "1.1.1.1",
            "protocol": "icmp",
            "interval_seconds": 30,
        },
    )

    assert response.status_code == 201

    created = response.json()
    assert created["name"] == "Cloudflare DNS"
    assert created["target"] == "1.1.1.1"
    assert created["protocol"] == "icmp"
    assert created["interval_seconds"] == 30

    response = client.get("/api/v1/targets")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == created["id"]


def test_reject_invalid_target(client):
    response = client.post(
        "/api/v1/targets",
        json={
            "name": "Invalid target",
            "target": "example.com",
            "protocol": "invalid",
        },
    )

    assert response.status_code == 422


def test_reject_invalid_interval(client):
    response = client.post(
        "/api/v1/targets",
        json={
            "name": "Invalid interval",
            "target": "1.1.1.1",
            "protocol": "icmp",
            "interval_seconds": 1,
        },
    )

    assert response.status_code == 422


def test_update_and_delete_target(client):
    create_response = client.post(
        "/api/v1/targets",
        json={
            "name": "Initial name",
            "target": "1.1.1.1",
            "protocol": "icmp",
        },
    )

    target_id = create_response.json()["id"]

    update_response = client.patch(
        f"/api/v1/targets/{target_id}",
        json={"name": "Updated name", "is_enabled": False},
    )

    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated name"
    assert update_response.json()["is_enabled"] is False

    delete_response = client.delete(f"/api/v1/targets/{target_id}")

    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/targets/{target_id}")
    assert get_response.status_code == 404
