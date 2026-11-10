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

    scheduled_scans = []

    monkeypatch.setattr(
        "app.api.routes.run_discovery_scan_background",
        lambda scan_id: scheduled_scans.append(scan_id),
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
        test_client.app.state.scheduled_scans = scheduled_scans
        test_client.app.state.testing_session_local = testing_session_local
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def create_scan(client, network_cidr="192.168.50.0/24"):
    response = client.post(
        "/api/v1/discovery/scans",
        json={"network_cidr": network_cidr},
    )
    assert response.status_code == 202
    return response.json()


def test_start_discovery_scan(client):
    scan = create_scan(client)

    assert scan["id"] is not None
    assert scan["network_cidr"] == "192.168.50.0/24"
    assert scan["status"] == "pending"
    assert scan["devices_found"] == 0
    assert scan["results"] == []
    assert client.app.state.scheduled_scans == [scan["id"]]


@pytest.mark.parametrize(
    "network_cidr",
    [
        "not-a-network",
        "2001:db8::/64",
        "192.168.0.0/23",
    ],
)
def test_reject_invalid_discovery_network(client, network_cidr):
    response = client.post(
        "/api/v1/discovery/scans",
        json={"network_cidr": network_cidr},
    )

    assert response.status_code == 422
    assert client.app.state.scheduled_scans == []


def test_reject_missing_network_cidr(client):
    response = client.post("/api/v1/discovery/scans", json={})

    assert response.status_code == 422


def test_list_discovery_scans(client):
    first = create_scan(client, "192.168.50.0/24")
    second = create_scan(client, "192.168.51.0/24")

    response = client.get("/api/v1/discovery/scans")

    assert response.status_code == 200
    scans = response.json()
    assert len(scans) == 2
    assert scans[0]["id"] == second["id"]
    assert scans[1]["id"] == first["id"]


def test_get_discovery_scan(client):
    created = create_scan(client)

    response = client.get(
        f"/api/v1/discovery/scans/{created['id']}"
    )

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["network_cidr"] == "192.168.50.0/24"


def test_get_missing_discovery_scan(client):
    response = client.get("/api/v1/discovery/scans/999")

    assert response.status_code == 404


def test_list_discovery_results_without_results(client):
    create_scan(client)

    response = client.get("/api/v1/discovery/results")

    assert response.status_code == 200
    assert response.json() == []


def test_list_discovery_results_for_missing_scan(client):
    response = client.get("/api/v1/discovery/results?scan_id=999")

    assert response.status_code == 404


def test_discovery_scan_list_limit_validation(client):
    response = client.get("/api/v1/discovery/scans?limit=101")

    assert response.status_code == 422


def test_discovery_results_limit_validation(client):
    response = client.get("/api/v1/discovery/results?limit=501")

    assert response.status_code == 422


def test_list_discovery_results_returns_persisted_results(client):
    from app.models import DiscoveryResult

    scan = create_scan(client)

    with client.app.state.testing_session_local() as db:
        db.add(
            DiscoveryResult(
                scan_id=scan["id"],
                ip_address="192.168.50.10",
                mac_address="AA:BB:CC:DD:EE:FF",
                hostname="nas-client",
                discovery_method="tcp",
                response_time_ms=2.5,
                open_ports=[22, 80, 443],
            )
        )
        db.commit()

    response = client.get(
        f"/api/v1/discovery/results?scan_id={scan['id']}"
    )

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["ip_address"] == "192.168.50.10"
    assert results[0]["device_name"] is None
    assert results[0]["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert results[0]["hostname"] == "nas-client"
    assert results[0]["discovery_method"] == "tcp"
    assert results[0]["response_time_ms"] == 2.5
    assert results[0]["icmp_latency_ms"] is None
    assert results[0]["icmp_is_available"] is None
    assert results[0]["icmp_error"] is None
    assert results[0]["open_ports"] == [22, 80, 443]


def create_discovery_result(client, **overrides):
    from app.models import DiscoveryResult

    scan = create_scan(client)
    values = {
        "scan_id": scan["id"],
        "ip_address": "192.168.50.10",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "hostname": "nas-client",
        "discovery_method": "tcp",
        "response_time_ms": 2.5,
        "open_ports": [22, 80],
    }
    values.update(overrides)

    with client.app.state.testing_session_local() as db:
        result = DiscoveryResult(**values)
        db.add(result)
        db.commit()
        db.refresh(result)
        return result.id


def test_enroll_discovery_result_creates_device(client):
    from app.models import Device, DiscoveryResult, MonitoringTarget

    result_id = create_discovery_result(client)

    response = client.post(
        f"/api/v1/discovery/results/{result_id}/enroll",
        json={"name": "NAS", "device_type": "server"},
    )

    assert response.status_code == 200
    device = response.json()
    assert device["name"] == "NAS"
    assert device["hostname"] == "nas-client"
    assert device["ip_address"] == "192.168.50.10"
    assert device["mac_address"] == "aa:bb:cc:dd:ee:ff"
    assert device["device_type"] == "server"

    with client.app.state.testing_session_local() as db:
        result = db.get(DiscoveryResult, result_id)
        assert result.device_id == device["id"]
        assert db.query(Device).count() == 1
        assert db.query(MonitoringTarget).count() == 0


def test_enroll_discovery_result_reuses_device_by_mac(client):
    from app.models import Device, DiscoveryResult

    result_id = create_discovery_result(client)

    with client.app.state.testing_session_local() as db:
        device = Device(
            name="Existing NAS",
            ip_address="192.168.50.20",
            mac_address="aa:bb:cc:dd:ee:ff",
        )
        db.add(device)
        db.commit()
        device_id = device.id

    response = client.post(
        f"/api/v1/discovery/results/{result_id}/enroll",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["id"] == device_id
    assert response.json()["name"] == "Existing NAS"
    assert response.json()["ip_address"] == "192.168.50.10"
    assert response.json()["hostname"] == "nas-client"

    with client.app.state.testing_session_local() as db:
        assert db.query(Device).count() == 1
        assert db.get(DiscoveryResult, result_id).device_id == device_id
        assert db.get(Device, device_id).last_seen_at is not None


def test_enroll_discovery_result_uses_ip_fallback(client):
    from app.models import Device, DiscoveryResult

    result_id = create_discovery_result(client, mac_address=None)

    with client.app.state.testing_session_local() as db:
        device = Device(
            name="Existing device",
            ip_address="192.168.50.10",
        )
        db.add(device)
        db.commit()
        device_id = device.id

    response = client.post(
        f"/api/v1/discovery/results/{result_id}/enroll",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["id"] == device_id

    with client.app.state.testing_session_local() as db:
        assert db.query(Device).count() == 1
        assert db.get(DiscoveryResult, result_id).device_id == device_id


def test_enroll_discovery_result_rejects_conflicting_matches(client):
    from app.models import Device

    result_id = create_discovery_result(client)

    with client.app.state.testing_session_local() as db:
        db.add_all(
            [
                Device(
                    name="MAC match",
                    mac_address="aa:bb:cc:dd:ee:ff",
                ),
                Device(
                    name="IP match",
                    ip_address="192.168.50.10",
                ),
            ]
        )
        db.commit()

    response = client.post(
        f"/api/v1/discovery/results/{result_id}/enroll",
        json={},
    )

    assert response.status_code == 409
    assert "different" in response.json()["detail"]


def test_enroll_discovery_result_reuses_device_by_hostname(client):
    from app.models import Device, DiscoveryResult

    result_id = create_discovery_result(client, mac_address=None)

    with client.app.state.testing_session_local() as db:
        device = Device(
            name="Existing NAS",
            hostname="NAS-CLIENT.",
            ip_address="192.168.50.20",
        )
        db.add(device)
        db.commit()
        device_id = device.id

    response = client.post(
        f"/api/v1/discovery/results/{result_id}/enroll",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["id"] == device_id
    assert response.json()["ip_address"] == "192.168.50.10"
    assert response.json()["hostname"] == "nas-client"

    with client.app.state.testing_session_local() as db:
        assert db.query(Device).count() == 1
        assert db.get(DiscoveryResult, result_id).device_id == device_id


def test_enroll_discovery_result_rejects_ip_match_with_different_known_mac(client):
    from app.models import Device

    result_id = create_discovery_result(client)

    with client.app.state.testing_session_local() as db:
        db.add(
            Device(
                name="Different device",
                ip_address="192.168.50.10",
                mac_address="11:22:33:44:55:66",
            )
        )
        db.commit()

    response = client.post(
        f"/api/v1/discovery/results/{result_id}/enroll",
        json={},
    )

    assert response.status_code == 409
    assert "MAC" in response.json()["detail"]


def test_enroll_discovery_result_is_idempotent(client):
    from app.models import Device, DiscoveryResult

    result_id = create_discovery_result(client)

    with client.app.state.testing_session_local() as db:
        device = Device(name="Already enrolled")
        db.add(device)
        db.commit()
        device_id = device.id

        result = db.get(DiscoveryResult, result_id)
        result.device_id = device_id
        db.commit()

    response = client.post(
        f"/api/v1/discovery/results/{result_id}/enroll",
        json={"name": "A different name"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == device_id
    assert response.json()["name"] == "A different name"

    with client.app.state.testing_session_local() as db:
        assert db.query(Device).count() == 1
        assert db.get(Device, device_id).name == "A different name"


def test_enroll_missing_discovery_result_returns_404(client):
    response = client.post(
        "/api/v1/discovery/results/999/enroll",
        json={},
    )

    assert response.status_code == 404
