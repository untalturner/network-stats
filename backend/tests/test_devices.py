import pytest
from datetime import datetime

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


def create_device(client):
    response = client.post(
        "/api/v1/devices",
        json={
            "name": "TrueNAS",
            "hostname": "yoda",
            "ip_address": "192.168.50.250",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "device_type": "server",
            "notes": "Main NAS",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_and_list_devices(client):
    created = create_device(client)

    assert created["name"] == "TrueNAS"
    assert created["hostname"] == "yoda"
    assert created["ip_address"] == "192.168.50.250"
    assert created["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert created["is_active"] is True

    response = client.get("/api/v1/devices")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == created["id"]


def test_get_device(client):
    created = create_device(client)

    response = client.get(f"/api/v1/devices/{created['id']}")

    assert response.status_code == 200
    assert response.json()["name"] == "TrueNAS"


def test_update_device(client):
    created = create_device(client)

    response = client.patch(
        f"/api/v1/devices/{created['id']}",
        json={
            "name": "Updated NAS",
            "ip_address": "2001:db8::1",
            "is_active": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated NAS"
    assert response.json()["ip_address"] == "2001:db8::1"
    assert response.json()["is_active"] is False


def test_reject_invalid_ip_address(client):
    response = client.post(
        "/api/v1/devices",
        json={
            "name": "Invalid device",
            "ip_address": "not-an-ip-address",
        },
    )

    assert response.status_code == 422


def test_reject_invalid_mac_address(client):
    response = client.post(
        "/api/v1/devices",
        json={
            "name": "Invalid device",
            "mac_address": "not-a-mac-address",
        },
    )

    assert response.status_code == 422


def test_delete_device_preserves_monitoring_target(client):
    device = create_device(client)

    target_response = client.post(
        "/api/v1/targets",
        json={
            "name": "NAS connectivity",
            "target": "192.168.50.250",
            "protocol": "icmp",
            "device_id": device["id"],
        },
    )
    assert target_response.status_code == 201
    target_id = target_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/devices/{device['id']}"
    )
    assert delete_response.status_code == 204

    target_response = client.get(f"/api/v1/targets/{target_id}")

    assert target_response.status_code == 200
    assert target_response.json()["device_id"] is None


def test_missing_device_returns_404(client):
    response = client.get("/api/v1/devices/999")

    assert response.status_code == 404


def test_delete_missing_device_returns_404(client):
    response = client.delete("/api/v1/devices/999")

    assert response.status_code == 404


def test_filter_devices_by_search(client):
    create_device(client)

    client.post(
        "/api/v1/devices",
        json={
            "name": "Living Room TV",
            "hostname": "living-room",
            "ip_address": "192.168.50.20",
            "device_type": "tv",
        },
    )

    response = client.get("/api/v1/devices?search=TRUENAS")

    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1
    assert devices[0]["name"] == "TrueNAS"


def test_filter_devices_by_device_type(client):
    create_device(client)

    client.post(
        "/api/v1/devices",
        json={
            "name": "Living Room TV",
            "device_type": "tv",
        },
    )

    response = client.get("/api/v1/devices?device_type=tv")

    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1
    assert devices[0]["name"] == "Living Room TV"


def test_filter_devices_by_active_status(client):
    create_device(client)

    client.post(
        "/api/v1/devices",
        json={
            "name": "Offline device",
            "is_active": False,
        },
    )

    response = client.get("/api/v1/devices?is_active=false")

    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1
    assert devices[0]["name"] == "Offline device"


def test_combine_device_filters(client):
    create_device(client)

    client.post(
        "/api/v1/devices",
        json={
            "name": "Living Room TV",
            "hostname": "living-room",
            "device_type": "tv",
            "is_active": True,
        },
    )

    client.post(
        "/api/v1/devices",
        json={
            "name": "Old TV",
            "device_type": "tv",
            "is_active": False,
        },
    )

    response = client.get(
        "/api/v1/devices?search=tv&device_type=tv&is_active=true"
    )

    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1
    assert devices[0]["name"] == "Living Room TV"


def test_paginate_devices(client):
    for index in range(5):
        response = client.post(
            "/api/v1/devices",
            json={"name": f"Device {index}"},
        )
        assert response.status_code == 201

    first_page = client.get("/api/v1/devices?limit=2&offset=0")
    second_page = client.get("/api/v1/devices?limit=2&offset=2")
    third_page = client.get("/api/v1/devices?limit=2&offset=4")

    assert [device["name"] for device in first_page.json()] == [
        "Device 0",
        "Device 1",
    ]
    assert [device["name"] for device in second_page.json()] == [
        "Device 2",
        "Device 3",
    ]
    assert [device["name"] for device in third_page.json()] == ["Device 4"]


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=501",
        "offset=-1",
        "search=",
        "device_type=",
    ],
)
def test_reject_invalid_device_filters(client, query):
    response = client.get(f"/api/v1/devices?{query}")

    assert response.status_code == 422


def test_device_filters_return_empty_list_when_no_match(client):
    create_device(client)

    response = client.get("/api/v1/devices?device_type=router")

    assert response.status_code == 200
    assert response.json() == []


def create_device_target(client, device_id, name="Connectivity check", enabled=True):
    response = client.post(
        "/api/v1/targets",
        json={
            "name": name,
            "target": "192.168.50.1",
            "protocol": "icmp",
            "device_id": device_id,
        },
    )
    assert response.status_code == 201
    target = response.json()

    if not enabled:
        update_response = client.patch(
            f"/api/v1/targets/{target['id']}",
            json={"is_enabled": False},
        )
        assert update_response.status_code == 200

    return target


def add_measurement(target_id, is_available, measured_at=None):
    from datetime import datetime

    from app.models import Measurement

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        measurement = Measurement(
            target_id=target_id,
            measured_at=measured_at or datetime(2026, 1, 1, 12, 0, 0),
            latency_ms=12.5 if is_available else None,
            packet_loss_percent=0.0 if is_available else 100.0,
            is_available=is_available,
            error=None if is_available else "Probe failed",
        )
        db.add(measurement)
        db.commit()
    finally:
        db.close()
        db_generator.close()


def get_device_status(client, device_id):
    return client.get(f"/api/v1/devices/{device_id}/status")


def test_device_status_is_unknown_without_targets(client):
    device = create_device(client)

    response = get_device_status(client, device["id"])

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unknown"
    assert data["enabled_targets"] == 0
    assert data["available_targets"] == 0
    assert data["unavailable_targets"] == 0
    assert data["targets"] == []


def test_device_status_is_unknown_without_measurements(client):
    device = create_device(client)
    create_device_target(client, device["id"])

    response = get_device_status(client, device["id"])

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unknown"
    assert data["enabled_targets"] == 1
    assert data["available_targets"] == 0
    assert data["unavailable_targets"] == 0
    assert data["targets"][0]["latest_measurement"] is None


def test_device_status_is_online_when_all_targets_are_available(client):
    device = create_device(client)
    target = create_device_target(client, device["id"])
    add_measurement(target["id"], is_available=True)

    response = get_device_status(client, device["id"])

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["enabled_targets"] == 1
    assert data["available_targets"] == 1
    assert data["unavailable_targets"] == 0
    assert data["targets"][0]["latest_measurement"]["is_available"] is True


def test_device_status_is_offline_when_all_targets_are_unavailable(client):
    device = create_device(client)
    target = create_device_target(client, device["id"])
    add_measurement(target["id"], is_available=False)

    response = get_device_status(client, device["id"])

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "offline"
    assert data["enabled_targets"] == 1
    assert data["available_targets"] == 0
    assert data["unavailable_targets"] == 1


def test_device_status_is_degraded_when_targets_have_mixed_availability(client):
    device = create_device(client)
    available_target = create_device_target(
        client, device["id"], name="Router"
    )
    unavailable_target = create_device_target(
        client, device["id"], name="External host"
    )
    add_measurement(available_target["id"], is_available=True)
    add_measurement(unavailable_target["id"], is_available=False)

    response = get_device_status(client, device["id"])

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["enabled_targets"] == 2
    assert data["available_targets"] == 1
    assert data["unavailable_targets"] == 1


def test_disabled_targets_do_not_affect_device_status(client):
    device = create_device(client)
    enabled_target = create_device_target(
        client, device["id"], name="Enabled target"
    )
    disabled_target = create_device_target(
        client, device["id"], name="Disabled target", enabled=False
    )
    add_measurement(enabled_target["id"], is_available=True)
    add_measurement(disabled_target["id"], is_available=False)

    response = get_device_status(client, device["id"])

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["enabled_targets"] == 1
    assert data["available_targets"] == 1
    assert data["unavailable_targets"] == 0
    assert len(data["targets"]) == 2
    assert data["targets"][1]["is_enabled"] is False


def test_device_status_uses_latest_measurement(client):
    device = create_device(client)
    target = create_device_target(client, device["id"])

    add_measurement(
        target["id"],
        is_available=False,
        measured_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    add_measurement(
        target["id"],
        is_available=True,
        measured_at=datetime(2026, 1, 2, 12, 0, 0),
    )

    response = get_device_status(client, device["id"])

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["available_targets"] == 1
    assert data["targets"][0]["latest_measurement"]["is_available"] is True


def test_device_status_returns_404_for_missing_device(client):
    response = get_device_status(client, 999)

    assert response.status_code == 404
