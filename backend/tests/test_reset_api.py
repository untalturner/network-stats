import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.dependencies import get_db
from app.database import Base
from app.main import app
from app.models import AppSetting, Device
from app.services.scheduler import monitoring_scheduler


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(monitoring_scheduler, "start", lambda: None)
    monkeypatch.setattr(monitoring_scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(monitoring_scheduler, "reconcile", lambda: None)
    monkeypatch.setattr(
        "app.main.recover_interrupted_discovery_scans",
        lambda db: None,
    )

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
        test_client.app.state.testing_session_local = testing_session_local
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_reset_requires_exact_confirmation(client):
    response = client.post(
        "/api/v1/system/reset",
        json={"confirmation": "reset"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == 'Confirmation must be exactly "RESET".'


def test_reset_does_not_clear_data_if_backup_fails(client, monkeypatch):
    with client.app.state.testing_session_local() as db:
        db.add(Device(name="Keep this device", ip_address="192.168.50.20"))
        db.commit()

    def fail_backup():
        raise RuntimeError("Simulated backup failure")

    monkeypatch.setattr("app.api.routes.create_database_backup", fail_backup)

    response = client.post(
        "/api/v1/system/reset",
        json={"confirmation": "RESET"},
    )

    assert response.status_code == 500
    assert "backup failed" in response.json()["detail"].lower()

    with client.app.state.testing_session_local() as db:
        assert db.query(Device).count() == 1


def test_reset_clears_application_data_and_returns_backup_name(
    client,
    monkeypatch,
    tmp_path,
):
    backup_path = tmp_path / "network_stats_before_reset_test.db"
    backup_path.write_bytes(b"test backup")

    with client.app.state.testing_session_local() as db:
        db.add_all(
            [
                Device(name="Test device", ip_address="192.168.50.20"),
                AppSetting(key="test_setting", value="test_value"),
            ]
        )
        db.commit()

    monkeypatch.setattr(
        "app.api.routes.create_database_backup",
        lambda: backup_path,
    )

    response = client.post(
        "/api/v1/system/reset",
        json={"confirmation": "RESET"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "reset"
    assert response.json()["backup_file"] == backup_path.name
    assert backup_path.is_file()

    with client.app.state.testing_session_local() as db:
        for table in reversed(Base.metadata.sorted_tables):
            assert db.execute(table.select()).all() == []
