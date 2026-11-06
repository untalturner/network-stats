import asyncio
import ipaddress
import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.discovery import (
    DEFAULT_DISCOVERY_PORTS,
    discover_tcp_hosts,
    discover_mdns_hosts,
    discover_ssdp_hosts,
    lookup_hostname,
    lookup_mac_address,
    validate_network,
)
from app.models import Device, DiscoveryResult, DiscoveryScan
from app.probes import probe_icmp

logger = logging.getLogger(__name__)

ENRICHMENT_TIMEOUT_SECONDS = 1.5
ENRICHMENT_CONCURRENCY = 20
ICMP_CONCURRENCY = 20
ICMP_TIMEOUT_SECONDS = 1.0


INTERRUPTED_SCAN_ERROR = "Scan interrupted because the application restarted"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)



async def discover_icmp_hosts(
    network_cidr: str,
) -> dict[str, object]:
    """Probe every usable IPv4 address and return its ICMP result."""
    network = validate_network(network_cidr)
    semaphore = asyncio.Semaphore(ICMP_CONCURRENCY)

    async def probe_address(ip_address: str):
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    probe_icmp(
                        ip_address,
                        timeout_seconds=ICMP_TIMEOUT_SECONDS,
                    ),
                    timeout=ICMP_TIMEOUT_SECONDS + 1.5,
                )
            except Exception as exc:
                logger.debug(
                    "ICMP discovery probe failed for %s",
                    ip_address,
                    exc_info=True,
                )
                return exc

    addresses = [str(ip) for ip in network.hosts()]
    results = await asyncio.gather(
        *(probe_address(address) for address in addresses)
    )
    return dict(zip(addresses, results))


def find_existing_device_id(
    db: Session,
    ip_address: str,
    mac_address: str | None,
) -> int | None:
    """Match a discovered host to one unambiguous, already-enrolled device."""
    conditions = [Device.ip_address == ip_address]

    if mac_address:
        conditions.append(func.lower(Device.mac_address) == mac_address.lower())

    matches = db.scalars(
        select(Device.id).where(or_(*conditions)).distinct()
    ).all()

    # Do not guess if the IP and MAC identify different devices, or if
    # duplicate records make the match ambiguous.
    return matches[0] if len(matches) == 1 else None


def create_discovery_scan(db: Session, network_cidr: str) -> DiscoveryScan:
    """Validate and persist a pending network discovery scan."""
    network = validate_network(network_cidr)

    scan = DiscoveryScan(
        network_cidr=str(network),
        status="pending",
        devices_found=0,
    )
    db.add(scan)

    try:
        db.commit()
        db.refresh(scan)
    except Exception:
        db.rollback()
        raise

    return scan


async def execute_discovery_scan(
    db: Session,
    scan_id: int,
    ports: tuple[int, ...] = DEFAULT_DISCOVERY_PORTS,
) -> DiscoveryScan:
    """Atomically claim and execute a pending discovery scan."""
    claim = db.execute(
        update(DiscoveryScan)
        .where(
            DiscoveryScan.id == scan_id,
            DiscoveryScan.status == "pending",
        )
        .values(
            status="running",
            started_at=utc_now(),
            finished_at=None,
            error=None,
        )
        .execution_options(synchronize_session=False)
    )

    if claim.rowcount != 1:
        db.rollback()
        scan = db.get(DiscoveryScan, scan_id)

        if scan is None:
            raise LookupError("Discovery scan not found")

        raise ValueError("Only pending discovery scans can be executed")

    try:
        db.commit()

        scan = db.get(DiscoveryScan, scan_id)
        if scan is None:
            raise LookupError("Discovery scan not found")

        tcp_hosts = await discover_tcp_hosts(
            network_cidr=scan.network_cidr,
            ports=ports,
        )
        tcp_hosts_by_ip = {host.ip_address: host for host in tcp_hosts}

        # ICMP discovery is independent of TCP port availability.
        icmp_results_by_ip = await discover_icmp_hosts(scan.network_cidr)

        # SSDP can find devices that do not answer TCP or ICMP probes.
        try:
            ssdp_responses = await discover_ssdp_hosts()
        except Exception:
            logger.debug("SSDP discovery failed", exc_info=True)
            ssdp_responses = {}

        # Only accept SSDP responders inside the network being scanned.
        network = validate_network(scan.network_cidr)
        ssdp_hosts_by_ip = {}
        for ip_address, headers in ssdp_responses.items():
            try:
                parsed_ip = ipaddress.ip_address(ip_address)
            except ValueError:
                continue
            if isinstance(parsed_ip, ipaddress.IPv4Address) and parsed_ip in network:
                ssdp_hosts_by_ip[str(parsed_ip)] = headers

        discovered_ips = set(tcp_hosts_by_ip)
        discovered_ips.update(
            ip_address
            for ip_address, result in icmp_results_by_ip.items()
            if hasattr(result, "is_available") and result.is_available
        )
        discovered_ips.update(ssdp_hosts_by_ip)

        hosts = []
        for ip_address in sorted(
            discovered_ips,
            key=lambda value: tuple(int(part) for part in value.split(".")),
        ):
            tcp_host = tcp_hosts_by_ip.get(ip_address)
            hosts.append(
                type("DiscoveredHostRecord", (), {
                    "ip_address": ip_address,
                    "open_ports": tcp_host.open_ports if tcp_host else (),
                    "response_time_ms": (
                        tcp_host.response_time_ms if tcp_host else None
                    ),
                })()
            )

        # mDNS is a subnet-wide lookup, so run it once rather than once per host.
        try:
            mdns_hostnames = await discover_mdns_hosts()
        except Exception:
            logger.debug("mDNS discovery failed; using reverse DNS fallback", exc_info=True)
            mdns_hostnames = {}

        enrichment_semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)

        async def enrich_host(host):
            async with enrichment_semaphore:
                async def lookup(function):
                    try:
                        return await asyncio.wait_for(
                            asyncio.to_thread(function, host.ip_address),
                            timeout=ENRICHMENT_TIMEOUT_SECONDS,
                        )
                    except Exception:
                        logger.debug(
                            "Discovery enrichment failed for %s",
                            host.ip_address,
                            exc_info=True,
                        )
                        return None

                mac_address = await lookup(lookup_mac_address)
                hostname = mdns_hostnames.get(host.ip_address)
                if not hostname:
                    hostname = await lookup(lookup_hostname)

                return mac_address, hostname

        enriched_hosts = await asyncio.gather(
            *(enrich_host(host) for host in hosts)
        )

        # Reuse the subnet sweep result. TCP-only hosts still receive an
        # ICMP measurement so their two measurements remain independent.
        async def probe_tcp_host_icmp(host):
            if host.ip_address in icmp_results_by_ip:
                return icmp_results_by_ip[host.ip_address]
            try:
                return await asyncio.wait_for(
                    probe_icmp(
                        host.ip_address,
                        timeout_seconds=ICMP_TIMEOUT_SECONDS,
                    ),
                    timeout=ICMP_TIMEOUT_SECONDS + 1.5,
                )
            except Exception as exc:
                logger.debug(
                    "ICMP discovery probe failed for %s",
                    host.ip_address,
                    exc_info=True,
                )
                return exc

        icmp_results = await asyncio.gather(
            *(probe_tcp_host_icmp(host) for host in hosts)
        )

        discovery_results = []
        for host, (mac_address, hostname), icmp_result in zip(
            hosts, enriched_hosts, icmp_results
        ):
            existing_device_id = find_existing_device_id(
                db,
                ip_address=host.ip_address,
                mac_address=mac_address,
            )

            resolved_mac_address = mac_address.lower() if mac_address else None

            if existing_device_id is not None:
                existing_device = db.get(Device, existing_device_id)
                if existing_device is not None:
                    # An IP match must not override a different known MAC.
                    if (
                        mac_address
                        and existing_device.mac_address
                        and existing_device.mac_address.lower() != mac_address.lower()
                    ):
                        existing_device_id = None
                    else:
                        # Preserve a known MAC when the current scan cannot resolve it.
                        resolved_mac_address = (
                            resolved_mac_address or existing_device.mac_address
                        )
                        if resolved_mac_address and not existing_device.mac_address:
                            existing_device.mac_address = resolved_mac_address

                        # A MAC match is reliable enough to follow a changed DHCP IP.
                        if mac_address:
                            existing_device.ip_address = host.ip_address

                        existing_device.last_seen_at = utc_now()

            discovery_results.append(
                DiscoveryResult(
                    scan_id=scan.id,
                    device_id=existing_device_id,
                    ip_address=host.ip_address,
                    mac_address=resolved_mac_address,
                    hostname=hostname,
                    discovery_method=(
                        "tcp"
                        if host.open_ports
                        else "icmp"
                        if (
                            hasattr(icmp_result, "is_available")
                            and icmp_result.is_available
                        )
                        else "ssdp"
                    ),
                    response_time_ms=host.response_time_ms,
                    icmp_latency_ms=(
                        icmp_result.latency_ms
                        if hasattr(icmp_result, "is_available")
                        and icmp_result.is_available
                        else None
                    ),
                    icmp_is_available=(
                        icmp_result.is_available
                        if hasattr(icmp_result, "is_available")
                        else False
                    ),
                    icmp_error=(
                        icmp_result.error
                        if hasattr(icmp_result, "is_available")
                        and not icmp_result.is_available
                        else str(icmp_result)[:500]
                        if isinstance(icmp_result, Exception)
                        else None
                    ),
                    open_ports=list(host.open_ports),
                )
            )

        db.add_all(discovery_results)

        scan.devices_found = len(hosts)
        scan.status = "completed"
        scan.finished_at = utc_now()

        db.commit()
        db.refresh(scan)

        logger.info(
            "Discovery scan %s completed: %s hosts found on %s",
            scan.id,
            scan.devices_found,
            scan.network_cidr,
        )

        return scan

    except Exception as exc:
        db.rollback()

        failed_scan = db.get(DiscoveryScan, scan_id)
        if failed_scan is not None and failed_scan.status == "running":
            failed_scan.status = "failed"
            failed_scan.finished_at = utc_now()
            failed_scan.error = str(exc)[:2000]

            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "Could not persist failure for discovery scan %s",
                    scan_id,
                )

        logger.exception("Discovery scan %s failed", scan_id)
        raise


def recover_interrupted_discovery_scans(db: Session) -> int:
    """Mark scans left pending or running by a previous process as failed."""
    result = db.execute(
        update(DiscoveryScan)
        .where(DiscoveryScan.status.in_(("pending", "running")))
        .values(
            status="failed",
            finished_at=utc_now(),
            error=INTERRUPTED_SCAN_ERROR,
        )
        .execution_options(synchronize_session=False)
    )

    db.commit()
    recovered = result.rowcount or 0

    if recovered:
        logger.warning(
            "Marked %s interrupted discovery scan(s) as failed",
            recovered,
        )

    return recovered


def run_discovery_scan_background(scan_id: int) -> None:
    """Execute a discovery scan using an independent database session."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        try:
            asyncio.run(execute_discovery_scan(db, scan_id))
        except Exception:
            logger.exception("Background discovery scan %s failed", scan_id)
