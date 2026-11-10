from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.database import Base
from app.models import Device
from app.services.device_identity import (
    normalize_hostname,
    normalize_mac_address,
    resolve_device_identity,
    update_device_observation,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False)
    session = testing_session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_normalize_mac_and_hostname():
    assert normalize_mac_address("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac_address("aabb.ccdd.eeff") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac_address("invalid") is None
    assert normalize_hostname(" NAS-CLIENT.LOCAL. ") == "nas-client.local"


def test_resolves_device_by_mac_after_ip_change(db):
    device = Device(
        name="Router",
        ip_address="192.168.50.10",
        mac_address="AA:BB:CC:DD:EE:FF",
    )
    db.add(device)
    db.commit()

    resolution = resolve_device_identity(
        db,
        ip_address="192.168.50.20",
        mac_address="aa-bb-cc-dd-ee-ff",
        hostname=None,
    )

    assert resolution.device.id == device.id
    assert resolution.matched_by == ("mac",)
    assert resolution.conflict is False


def test_resolves_device_by_hostname_after_ip_change(db):
    device = Device(
        name="NAS",
        hostname="NAS-CLIENT.",
        ip_address="192.168.50.10",
    )
    db.add(device)
    db.commit()

    resolution = resolve_device_identity(
        db,
        ip_address="192.168.50.20",
        mac_address=None,
        hostname="nas-client",
    )

    assert resolution.device.id == device.id
    assert resolution.matched_by == ("hostname",)


def test_conflicts_when_mac_and_ip_match_different_devices(db):
    db.add_all([
        Device(
            name="MAC match",
            ip_address="192.168.50.11",
            mac_address="aa:bb:cc:dd:ee:ff",
        ),
        Device(
            name="IP match",
            ip_address="192.168.50.10",
            mac_address="11:22:33:44:55:66",
        ),
    ])
    db.commit()

    resolution = resolve_device_identity(
        db,
        ip_address="192.168.50.10",
        mac_address="aa:bb:cc:dd:ee:ff",
        hostname=None,
    )

    assert resolution.device is None
    assert resolution.conflict is True
    assert "different" in resolution.reason


def test_conflicts_when_ip_matches_a_different_known_mac(db):
    db.add(
        Device(
            name="Existing device",
            ip_address="192.168.50.10",
            mac_address="11:22:33:44:55:66",
        )
    )
    db.commit()

    resolution = resolve_device_identity(
        db,
        ip_address="192.168.50.10",
        mac_address="aa:bb:cc:dd:ee:ff",
        hostname=None,
    )

    assert resolution.device is None
    assert resolution.conflict is True
    assert "MAC" in resolution.reason


def test_conflicts_when_hostname_matches_multiple_devices(db):
    db.add_all([
        Device(name="First", hostname="nas-client", ip_address="192.168.50.10"),
        Device(name="Second", hostname="NAS-CLIENT.", ip_address="192.168.50.20"),
    ])
    db.commit()

    resolution = resolve_device_identity(
        db,
        ip_address="192.168.50.30",
        mac_address=None,
        hostname="nas-client",
    )

    assert resolution.device is None
    assert resolution.conflict is True
    assert "Multiple" in resolution.reason


def test_stale_or_conflicting_observation_does_not_overwrite_device(db):
    latest = datetime(2026, 11, 10, 12, 0, 0)
    device = Device(
        name="NAS",
        hostname="nas-client",
        ip_address="192.168.50.20",
        mac_address="aa:bb:cc:dd:ee:ff",
        last_seen_at=latest,
    )
    db.add(device)
    db.commit()

    assert not update_device_observation(
        device,
        ip_address="192.168.50.10",
        mac_address="aa:bb:cc:dd:ee:ff",
        hostname="old-hostname",
        observed_at=latest - timedelta(minutes=5),
    )
    assert not update_device_observation(
        device,
        ip_address="192.168.50.10",
        mac_address="11:22:33:44:55:66",
        hostname="other-device",
        observed_at=latest + timedelta(minutes=5),
    )

    assert device.ip_address == "192.168.50.20"
    assert device.mac_address == "aa:bb:cc:dd:ee:ff"
    assert device.hostname == "nas-client"
    assert device.last_seen_at == latest
