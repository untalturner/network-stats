from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.database import Base
from app.discovery import DiscoveredHost
from app.models import Device, DiscoveryResult, DiscoveryScan
from app.probes import ProbeResult
from app.services.discovery import (
    create_discovery_scan,
    execute_discovery_scan,
)


@pytest.fixture(autouse=True)
def mock_icmp_probe():
    result = ProbeResult(
        target="192.168.50.10",
        protocol="icmp",
        is_available=True,
        latency_ms=1.25,
        packet_loss_percent=0.0,
        measured_at=datetime.utcnow(),
    )
    with (
        patch(
            "app.services.discovery.probe_icmp",
            new_callable=AsyncMock,
            return_value=result,
        ) as mock,
        patch(
            "app.services.discovery.discover_icmp_hosts",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "app.services.discovery.discover_mdns_hosts",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "app.services.discovery.discover_ssdp_hosts",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "app.services.discovery.get_local_interface_addresses",
            return_value={},
        ),
    ):
        yield mock


@pytest.fixture
def session_factory():
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

    yield testing_session_local

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_create_discovery_scan_persists_pending_scan(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")

        assert scan.id is not None
        assert scan.network_cidr == "192.168.50.0/24"
        assert scan.status == "pending"
        assert scan.devices_found == 0
        assert scan.started_at is None
        assert scan.finished_at is None


def test_create_discovery_scan_rejects_invalid_network(session_factory):
    with session_factory() as db:
        with pytest.raises(ValueError, match="Invalid network CIDR"):
            create_discovery_scan(db, "not-a-network")

        assert db.scalar(select(DiscoveryScan)) is None


@pytest.mark.asyncio
async def test_execute_discovery_scan_persists_results(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        scan_id = scan.id

        discovered_hosts = [
            DiscoveredHost(
                ip_address="192.168.50.10",
                open_ports=(22, 80),
                response_time_ms=2.5,
            ),
            DiscoveredHost(
                ip_address="192.168.50.20",
                open_ports=(443,),
                response_time_ms=4.2,
            ),
        ]

        with patch(
            "app.services.discovery.discover_tcp_hosts",
            new_callable=AsyncMock,
            return_value=discovered_hosts,
        ) as mock_discover:
            completed = await execute_discovery_scan(db, scan_id)

        mock_discover.assert_awaited_once_with(
            network_cidr="192.168.50.0/24",
            ports=(22, 53, 80, 443, 445, 554, 631, 8000, 8080, 8443, 9100),
        )

        assert completed.status == "completed"
        assert completed.devices_found == 2
        assert completed.started_at is not None
        assert completed.finished_at is not None
        assert completed.error is None

        results = db.scalars(
            select(DiscoveryResult)
            .where(DiscoveryResult.scan_id == scan_id)
            .order_by(DiscoveryResult.ip_address)
        ).all()

        assert len(results) == 2
        assert results[0].ip_address == "192.168.50.10"
        assert results[0].discovery_method == "tcp"
        assert results[0].response_time_ms == 2.5
        assert results[0].icmp_latency_ms == 1.25
        assert results[0].icmp_is_available is True
        assert results[0].icmp_error is None
        assert results[0].is_this_device is False
        assert results[0].open_ports == [22, 80]
        assert results[1].ip_address == "192.168.50.20"
        assert results[1].response_time_ms == 4.2
        assert results[1].open_ports == [443]

        assert db.scalar(select(Device)) is None




@pytest.mark.asyncio
async def test_ssdp_only_host_is_discovered(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")

        with (
            patch(
                "app.services.discovery.probe_icmp",
                new_callable=AsyncMock,
                side_effect=OSError("ICMP unavailable"),
            ),
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.discovery.discover_icmp_hosts",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.services.discovery.discover_ssdp_hosts",
                new_callable=AsyncMock,
                return_value={
                    "192.168.50.90": {
                        "location": "http://192.168.50.90:1900/device.xml",
                        "server": "Example UPnP Device",
                    }
                },
            ) as ssdp_lookup,
            patch(
                "app.services.discovery.discover_mdns_hosts",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("app.services.discovery.lookup_mac_address", return_value=None),
            patch("app.services.discovery.lookup_hostname", return_value=None),
        ):
            completed = await execute_discovery_scan(db, scan.id)

        result = db.scalar(
            select(DiscoveryResult).where(DiscoveryResult.scan_id == scan.id)
        )

        assert completed.status == "completed"
        assert completed.devices_found == 1
        assert result is not None
        assert result.ip_address == "192.168.50.90"
        assert result.discovery_method == "ssdp"
        assert result.open_ports == []
        assert result.device_id is None
        ssdp_lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_ssdp_responses_outside_scan_network_are_ignored(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")

        with (
            patch(
                "app.services.discovery.probe_icmp",
                new_callable=AsyncMock,
                side_effect=OSError("ICMP unavailable"),
            ),
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.discovery.discover_icmp_hosts",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.services.discovery.discover_ssdp_hosts",
                new_callable=AsyncMock,
                return_value={
                    "192.168.50.90": {"server": "Inside"},
                    "192.168.51.90": {"server": "Outside"},
                    "not-an-ip": {"server": "Invalid"},
                },
            ),
            patch(
                "app.services.discovery.discover_mdns_hosts",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("app.services.discovery.lookup_mac_address", return_value=None),
            patch("app.services.discovery.lookup_hostname", return_value=None),
        ):
            completed = await execute_discovery_scan(db, scan.id)

        results = db.scalars(
            select(DiscoveryResult).where(DiscoveryResult.scan_id == scan.id)
        ).all()

        assert completed.status == "completed"
        assert completed.devices_found == 1
        assert [result.ip_address for result in results] == ["192.168.50.90"]
        assert results[0].discovery_method == "ssdp"

@pytest.mark.asyncio
async def test_discovery_uses_mdns_hostname_before_reverse_dns(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        host = DiscoveredHost(
            ip_address="192.168.50.120",
            open_ports=(80,),
            response_time_ms=2.0,
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[host],
            ),
            patch(
                "app.services.discovery.discover_mdns_hosts",
                new_callable=AsyncMock,
                return_value={"192.168.50.120": "iphone.local"},
            ) as mdns_lookup,
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value=None,
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value="reverse-dns.example.local",
            ) as reverse_dns,
        ):
            await execute_discovery_scan(db, scan.id)

        result = db.scalar(
            select(DiscoveryResult).where(
                DiscoveryResult.scan_id == scan.id
            )
        )

        assert result is not None
        assert result.hostname == "iphone.local"
        mdns_lookup.assert_awaited_once()
        reverse_dns.assert_not_called()


@pytest.mark.asyncio
async def test_execute_discovery_scan_with_no_hosts(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")

        with patch(
            "app.services.discovery.discover_tcp_hosts",
            new_callable=AsyncMock,
            return_value=[],
        ):
            completed = await execute_discovery_scan(db, scan.id)

        assert completed.status == "completed"
        assert completed.devices_found == 0
        assert completed.results == []


@pytest.mark.asyncio
async def test_execute_discovery_scan_rejects_missing_scan(session_factory):
    with session_factory() as db:
        with pytest.raises(LookupError, match="Discovery scan not found"):
            await execute_discovery_scan(db, 999)


@pytest.mark.asyncio
async def test_execute_discovery_scan_rejects_non_pending_scan(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        scan.status = "completed"
        db.commit()

        with pytest.raises(ValueError, match="Only pending"):
            await execute_discovery_scan(db, scan.id)


@pytest.mark.asyncio
async def test_execute_discovery_scan_persists_failure(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        scan_id = scan.id

        with patch(
            "app.services.discovery.discover_tcp_hosts",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Simulated scanner failure"),
        ):
            with pytest.raises(RuntimeError, match="Simulated scanner failure"):
                await execute_discovery_scan(db, scan_id)

        db.expire_all()
        failed_scan = db.get(DiscoveryScan, scan_id)

        assert failed_scan.status == "failed"
        assert failed_scan.started_at is not None
        assert failed_scan.finished_at is not None
        assert failed_scan.error == "Simulated scanner failure"
        assert failed_scan.devices_found == 0
        assert failed_scan.results == []


@pytest.mark.asyncio
async def test_new_scan_recognizes_existing_device_by_mac(session_factory):
    with session_factory() as db:
        device = Device(
            name="Existing router",
            ip_address="192.168.50.10",
            mac_address="aa:bb:cc:dd:ee:ff",
        )
        db.add(device)
        db.commit()
        device_id = device.id

        scan = create_discovery_scan(db, "192.168.50.0/24")
        host = DiscoveredHost(
            ip_address="192.168.50.20",
            open_ports=(80,),
            response_time_ms=2.0,
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[host],
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value="aa:bb:cc:dd:ee:ff",
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
        ):
            await execute_discovery_scan(db, scan.id)

        result = db.scalar(
            select(DiscoveryResult).where(DiscoveryResult.scan_id == scan.id)
        )
        db.refresh(device)
        assert result.device_id == device_id
        assert device.last_seen_at is not None
        assert device.ip_address == "192.168.50.20"
        assert result.mac_address == "aa:bb:cc:dd:ee:ff"


@pytest.mark.asyncio
async def test_new_scan_recognizes_existing_device_by_ip_without_mac(
    session_factory,
):
    with session_factory() as db:
        device = Device(
            name="Existing device",
            ip_address="192.168.50.10",
        )
        db.add(device)
        db.commit()
        device_id = device.id

        scan = create_discovery_scan(db, "192.168.50.0/24")
        host = DiscoveredHost(
            ip_address="192.168.50.10",
            open_ports=(443,),
            response_time_ms=3.0,
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[host],
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value=None,
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
        ):
            await execute_discovery_scan(db, scan.id)

        result = db.scalar(
            select(DiscoveryResult).where(DiscoveryResult.scan_id == scan.id)
        )
        assert result.device_id == device_id


@pytest.mark.asyncio
async def test_ip_match_learns_mac_and_updates_last_seen(session_factory):
    with session_factory() as db:
        device = Device(
            name="Existing device",
            ip_address="192.168.50.10",
        )
        db.add(device)
        db.commit()
        device_id = device.id

        scan = create_discovery_scan(db, "192.168.50.0/24")
        host = DiscoveredHost(
            ip_address="192.168.50.10",
            open_ports=(443,),
            response_time_ms=3.0,
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[host],
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value="aa:bb:cc:dd:ee:10",
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
        ):
            await execute_discovery_scan(db, scan.id)

        db.refresh(device)
        result = db.scalar(
            select(DiscoveryResult).where(DiscoveryResult.scan_id == scan.id)
        )
        assert result.device_id == device_id
        assert result.mac_address == "aa:bb:cc:dd:ee:10"
        assert device.mac_address == "aa:bb:cc:dd:ee:10"
        assert device.last_seen_at is not None


@pytest.mark.asyncio
async def test_ip_match_with_different_known_mac_is_not_linked(session_factory):
    with session_factory() as db:
        device = Device(
            name="Existing device",
            ip_address="192.168.50.10",
            mac_address="11:22:33:44:55:66",
        )
        db.add(device)
        db.commit()

        scan = create_discovery_scan(db, "192.168.50.0/24")
        host = DiscoveredHost(
            ip_address="192.168.50.10",
            open_ports=(80,),
            response_time_ms=2.0,
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[host],
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value="aa:bb:cc:dd:ee:ff",
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
        ):
            await execute_discovery_scan(db, scan.id)

        result = db.scalar(
            select(DiscoveryResult).where(DiscoveryResult.scan_id == scan.id)
        )
        assert result.device_id is None
        assert device.mac_address == "11:22:33:44:55:66"


@pytest.mark.asyncio
async def test_new_scan_leaves_conflicting_ip_and_mac_unlinked(session_factory):
    with session_factory() as db:
        db.add_all([
            Device(
                name="Device by MAC",
                ip_address="192.168.50.11",
                mac_address="aa:bb:cc:dd:ee:ff",
            ),
            Device(
                name="Device by IP",
                ip_address="192.168.50.10",
                mac_address="11:22:33:44:55:66",
            ),
        ])
        db.commit()

        scan = create_discovery_scan(db, "192.168.50.0/24")
        host = DiscoveredHost(
            ip_address="192.168.50.10",
            open_ports=(80,),
            response_time_ms=2.0,
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[host],
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value="aa:bb:cc:dd:ee:ff",
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
        ):
            await execute_discovery_scan(db, scan.id)

        result = db.scalar(
            select(DiscoveryResult).where(DiscoveryResult.scan_id == scan.id)
        )
        assert result.device_id is None


@pytest.mark.asyncio
async def test_new_scan_does_not_auto_enroll_unknown_device(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        host = DiscoveredHost(
            ip_address="192.168.50.99",
            open_ports=(8080,),
            response_time_ms=5.0,
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[host],
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value="aa:bb:cc:dd:ee:99",
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
        ):
            await execute_discovery_scan(db, scan.id)

        result = db.scalar(
            select(DiscoveryResult).where(DiscoveryResult.scan_id == scan.id)
        )
        assert result.device_id is None
        assert db.scalar(select(Device)) is None

@pytest.mark.asyncio
async def test_discovery_keeps_tcp_host_when_icmp_probe_fails(session_factory):
    failed_ping = ProbeResult(
        target="192.168.50.10",
        protocol="icmp",
        is_available=False,
        latency_ms=None,
        packet_loss_percent=100.0,
        measured_at=datetime.utcnow(),
        error="ICMP probe timed out",
    )

    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        host = DiscoveredHost(
            ip_address="192.168.50.10",
            open_ports=(80,),
            response_time_ms=3.5,
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[host],
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value=None,
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
            patch(
                "app.services.discovery.probe_icmp",
                new_callable=AsyncMock,
                return_value=failed_ping,
            ),
        ):
            completed = await execute_discovery_scan(db, scan.id)

        result = db.scalar(
            select(DiscoveryResult).where(
                DiscoveryResult.scan_id == scan.id
            )
        )

        assert completed.status == "completed"
        assert completed.devices_found == 1
        assert result is not None
        assert result.response_time_ms == 3.5
        assert result.icmp_latency_ms is None
        assert result.icmp_is_available is False
        assert result.icmp_error == "ICMP probe timed out"
        assert result.open_ports == [80]



@pytest.mark.asyncio
async def test_icmp_only_host_is_discovered_without_open_tcp_ports(session_factory):
    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        scan_id = scan.id

        ping_result = ProbeResult(
            target="192.168.50.120",
            protocol="icmp",
            is_available=True,
            latency_ms=9.1,
            packet_loss_percent=0.0,
            measured_at=datetime.utcnow(),
        )

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.discovery.discover_icmp_hosts",
                new_callable=AsyncMock,
                return_value={"192.168.50.120": ping_result},
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value=None,
            ),
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
        ):
            completed = await execute_discovery_scan(db, scan_id)

        result = db.scalar(
            select(DiscoveryResult).where(
                DiscoveryResult.scan_id == scan_id
            )
        )

        assert completed.status == "completed"
        assert completed.devices_found == 1
        assert result is not None
        assert result.ip_address == "192.168.50.120"
        assert result.discovery_method == "icmp"
        assert result.response_time_ms is None
        assert result.icmp_latency_ms == 9.1
        assert result.icmp_is_available is True
        assert result.open_ports == []
        assert result.device_id is None
        assert db.scalar(select(Device)) is None


@pytest.mark.parametrize("local_mac", ["aa:bb:cc:dd:ee:fa", None])
@pytest.mark.asyncio
async def test_discovery_includes_scanner_local_interface(session_factory, local_mac):
    local_ip = "192.168.50.250"

    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        scan_id = scan.id

        with (
            patch(
                "app.services.discovery.discover_tcp_hosts",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.discovery.get_local_interface_addresses",
                return_value={local_ip: local_mac},
            ),
            patch(
                "app.services.discovery.lookup_mac_address",
                return_value=None,
            ) as mac_lookup,
            patch(
                "app.services.discovery.lookup_hostname",
                return_value=None,
            ),
        ):
            completed = await execute_discovery_scan(db, scan_id)

        result = db.scalar(
            select(DiscoveryResult).where(
                DiscoveryResult.scan_id == scan_id
            )
        )

        assert completed.status == "completed"
        assert completed.devices_found == 1
        assert result is not None
        assert result.ip_address == local_ip
        assert result.mac_address == local_mac
        assert result.is_this_device is True
        assert result.device_id is None
        assert db.scalar(select(Device)) is None
        mac_lookup.assert_not_called()
