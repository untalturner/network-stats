import pytest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.database import Base
from app.models import DiscoveryScan
from app.services.discovery import (
    INTERRUPTED_SCAN_ERROR,
    create_discovery_scan,
    recover_interrupted_discovery_scans,
)


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


def test_recovery_marks_pending_and_running_scans_failed(session_factory):
    with session_factory() as db:
        pending = create_discovery_scan(db, "192.168.50.0/24")
        running = create_discovery_scan(db, "192.168.51.0/24")
        completed = create_discovery_scan(db, "192.168.52.0/24")
        failed = create_discovery_scan(db, "192.168.53.0/24")

        running.status = "running"
        completed.status = "completed"
        failed.status = "failed"
        db.commit()

        recovered = recover_interrupted_discovery_scans(db)

        assert recovered == 2

        db.expire_all()

        pending = db.get(DiscoveryScan, pending.id)
        running = db.get(DiscoveryScan, running.id)
        completed = db.get(DiscoveryScan, completed.id)
        failed = db.get(DiscoveryScan, failed.id)

        for scan in (pending, running):
            assert scan.status == "failed"
            assert scan.finished_at is not None
            assert scan.error == INTERRUPTED_SCAN_ERROR

        assert completed.status == "completed"
        assert failed.status == "failed"


def test_recovery_is_idempotent(session_factory):
    with session_factory() as db:
        create_discovery_scan(db, "192.168.50.0/24")

        assert recover_interrupted_discovery_scans(db) == 1
        assert recover_interrupted_discovery_scans(db) == 0


@pytest.mark.asyncio
async def test_scan_can_only_be_claimed_once(session_factory):
    from unittest.mock import AsyncMock, patch

    from app.discovery import DiscoveredHost
    from app.services.discovery import execute_discovery_scan

    with session_factory() as db:
        scan = create_discovery_scan(db, "192.168.50.0/24")
        scan_id = scan.id

        with patch(
            "app.services.discovery.discover_tcp_hosts",
            new_callable=AsyncMock,
            return_value=[
                DiscoveredHost(
                    ip_address="192.168.50.10",
                    open_ports=(80,),
                    response_time_ms=1.5,
                )
            ],
        ) as mock_discover:
            completed = await execute_discovery_scan(db, scan_id)

            assert completed.status == "completed"

            with pytest.raises(ValueError, match="Only pending"):
                await execute_discovery_scan(db, scan_id)

        mock_discover.assert_awaited_once()
