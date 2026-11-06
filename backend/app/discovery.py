import asyncio
import os
import ipaddress
import logging
import re
import socket
import struct
import time
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


DEFAULT_DISCOVERY_PORTS = (
    22,
    53,
    80,
    443,
    445,
    554,
    631,
    8000,
    8080,
    8443,
    9100,
)

MAX_CONCURRENT_CONNECTIONS = 100
DEFAULT_TIMEOUT_SECONDS = 0.5
MAX_NETWORK_ADDRESSES = 256
ARP_TABLE_PATH = os.getenv("NETWORK_STATS_ARP_TABLE_PATH", "/proc/net/arp")
MAC_ADDRESS_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


@dataclass(frozen=True)
class DiscoveredHost:
    ip_address: str
    open_ports: tuple[int, ...]
    response_time_ms: float | None


def validate_network(network_cidr: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(network_cidr, strict=False)
    except ValueError as exc:
        raise ValueError("Invalid network CIDR") from exc

    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Only IPv4 networks are supported")

    if network.num_addresses > MAX_NETWORK_ADDRESSES:
        raise ValueError("Network is too large; maximum supported size is /24")

    return network


async def _probe_port(
    ip_address: str,
    port: int,
    semaphore: asyncio.Semaphore,
    timeout_seconds: float,
) -> tuple[int, float] | None:
    async with semaphore:
        started = time.perf_counter()
        writer = None

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip_address, port),
                timeout=timeout_seconds,
            )

            latency_ms = (time.perf_counter() - started) * 1000
            return port, round(latency_ms, 3)

        except (OSError, asyncio.TimeoutError):
            return None

        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass


async def discover_tcp_hosts(
    network_cidr: str,
    ports: tuple[int, ...] = DEFAULT_DISCOVERY_PORTS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_concurrency: int = MAX_CONCURRENT_CONNECTIONS,
) -> list[DiscoveredHost]:
    """Discover IPv4 hosts accepting connections on selected TCP ports."""

    network = validate_network(network_cidr)

    if not ports:
        raise ValueError("At least one TCP port must be provided")

    if any(not isinstance(port, int) or not 1 <= port <= 65535 for port in ports):
        raise ValueError("TCP ports must be integers between 1 and 65535")

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    if max_concurrency < 1 or max_concurrency > MAX_CONCURRENT_CONNECTIONS:
        raise ValueError(
            f"max_concurrency must be between 1 and {MAX_CONCURRENT_CONNECTIONS}"
        )

    semaphore = asyncio.Semaphore(max_concurrency)

    async def scan_host(ip_address: str) -> DiscoveredHost | None:
        results = await asyncio.gather(
            *(
                _probe_port(ip_address, port, semaphore, timeout_seconds)
                for port in ports
            )
        )

        successful = [result for result in results if result is not None]

        if not successful:
            return None

        return DiscoveredHost(
            ip_address=ip_address,
            open_ports=tuple(sorted(port for port, _ in successful)),
            response_time_ms=min(latency for _, latency in successful),
        )

    hosts = await asyncio.gather(
        *(scan_host(str(ip)) for ip in network.hosts())
    )

    return sorted(
        (host for host in hosts if host is not None),
        key=lambda host: ipaddress.ip_address(host.ip_address),
    )



def lookup_mac_address(ip_address: str) -> str | None:
    """Return a complete MAC address from the Linux ARP cache, if available."""
    try:
        lines = Path(ARP_TABLE_PATH).read_text(encoding="ascii").splitlines()[1:]
    except (OSError, UnicodeError):
        return None

    for line in lines:
        fields = line.split()
        if len(fields) < 4 or fields[0] != ip_address:
            continue

        mac_address = fields[3]
        if (
            len(fields) >= 3
            and fields[2] != "0x0"
            and MAC_ADDRESS_PATTERN.fullmatch(mac_address)
            and mac_address.lower() != "00:00:00:00:00:00"
        ):
            return mac_address.lower()

    return None


def lookup_hostname(ip_address: str) -> str | None:
    """Return a reverse-DNS hostname, if one is available."""
    try:
        hostname = socket.gethostbyaddr(ip_address)[0].rstrip(".")
    except (OSError, socket.herror, socket.gaierror):
        return None

    if not hostname or len(hostname) > 255:
        return None

    return hostname

def _decode_dns_name(packet: bytes, offset: int) -> tuple[str, int]:
    """Decode a DNS name, including compressed names."""
    labels = []
    next_offset = None
    visited = set()

    while offset < len(packet):
        length = packet[offset]

        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                raise ValueError("Incomplete DNS compression pointer")
            pointer = ((length & 0x3F) << 8) | packet[offset + 1]
            if pointer in visited:
                raise ValueError("DNS compression pointer loop")
            visited.add(pointer)
            if next_offset is None:
                next_offset = offset + 2
            offset = pointer
            continue

        if length & 0xC0:
            raise ValueError("Unsupported DNS label encoding")

        offset += 1
        if length == 0:
            return ".".join(labels), next_offset or offset

        if offset + length > len(packet):
            raise ValueError("Incomplete DNS label")

        labels.append(packet[offset:offset + length].decode("utf-8"))
        offset += length

    raise ValueError("Incomplete DNS name")


def parse_mdns_ptr_response(packet: bytes) -> str | None:
    """Extract the first valid PTR target hostname from an mDNS response."""
    try:
        if len(packet) < 12:
            return None

        flags = struct.unpack_from("!H", packet, 2)[0]
        answer_count = struct.unpack_from("!H", packet, 6)[0]
        authority_count = struct.unpack_from("!H", packet, 8)[0]
        additional_count = struct.unpack_from("!H", packet, 10)[0]

        if not flags & 0x8000:
            return None

        offset = 12
        question_count = struct.unpack_from("!H", packet, 4)[0]

        for _ in range(question_count):
            _, offset = _decode_dns_name(packet, offset)
            offset += 4
            if offset > len(packet):
                return None

        for _ in range(answer_count + authority_count + additional_count):
            _, offset = _decode_dns_name(packet, offset)
            if offset + 10 > len(packet):
                return None

            record_type, record_class, ttl, data_length = struct.unpack_from(
                "!HHIH", packet, offset
            )
            offset += 10

            data_end = offset + data_length
            if data_end > len(packet):
                return None

            if record_type == 12 and record_class & 0x7FFF == 1:
                hostname, _ = _decode_dns_name(packet, offset)
                hostname = hostname.rstrip(".")
                if hostname and len(hostname) <= 255:
                    return hostname

            offset = data_end

    except (ValueError, UnicodeError, struct.error):
        return None

    return None

def parse_mdns_host_addresses(packet: bytes) -> dict[str, set[str]]:
    """Map advertised mDNS hostnames to IPv4 addresses in a DNS response."""
    try:
        if len(packet) < 12:
            return {}

        flags, question_count, answer_count, authority_count, additional_count = (
            struct.unpack_from("!HHHHH", packet, 2)
        )
        if not flags & 0x8000:
            return {}

        offset = 12
        for _ in range(question_count):
            _, offset = _decode_dns_name(packet, offset)
            offset += 4
            if offset > len(packet):
                return {}

        ptr_targets = {}
        srv_targets = {}
        addresses = {}

        record_count = answer_count + authority_count + additional_count
        for _ in range(record_count):
            owner, offset = _decode_dns_name(packet, offset)
            if offset + 10 > len(packet):
                return {}

            record_type, record_class, ttl, data_length = struct.unpack_from(
                "!HHIH", packet, offset
            )
            offset += 10
            data_end = offset + data_length
            if data_end > len(packet):
                return {}

            if record_class & 0x7FFF == 1:
                if record_type == 12:
                    target, _ = _decode_dns_name(packet, offset)
                    ptr_targets.setdefault(owner.lower(), set()).add(target.lower())

                elif record_type == 33 and data_length >= 7:
                    target, _ = _decode_dns_name(packet, offset + 6)
                    srv_targets.setdefault(owner.lower(), set()).add(target.lower())

                elif record_type == 1 and data_length == 4:
                    address = socket.inet_ntoa(packet[offset:data_end])
                    addresses.setdefault(owner.lower(), set()).add(address)

            offset = data_end

        # Follow PTR service instance -> SRV host -> A address.
        discovered = {}
        for instances in ptr_targets.values():
            for instance in instances:
                for hostname in srv_targets.get(instance, set()):
                    for address in addresses.get(hostname, set()):
                        discovered.setdefault(hostname.rstrip("."), set()).add(address)

        # Also include directly advertised host A records.
        for hostname, values in addresses.items():
            if hostname.endswith(".local"):
                discovered.setdefault(hostname.rstrip("."), set()).update(values)

        return discovered

    except (ValueError, UnicodeError, struct.error, OSError):
        return {}

MDNS_MULTICAST_GROUP = "224.0.0.251"
MDNS_PORT = 5353
MDNS_TIMEOUT_SECONDS = 2.0
MDNS_SERVICE_TYPES = (
    "_http._tcp.local",
    "_https._tcp.local",
    "_ipp._tcp.local",
    "_printer._tcp.local",
    "_airplay._tcp.local",
    "_raop._tcp.local",
    "_googlecast._tcp.local",
    "_hap._tcp.local",
    "_smb._tcp.local",
    "_ssh._tcp.local",
    "_device-info._tcp.local",
)


def build_mdns_ptr_query(service_type: str) -> bytes:
    """Build a DNS PTR query requesting a unicast mDNS response."""
    labels = service_type.rstrip(".").split(".")
    if not labels or any(not label or len(label.encode("utf-8")) > 63 for label in labels):
        raise ValueError("Invalid mDNS service name")

    question_name = b"".join(
        bytes([len(label.encode("utf-8"))]) + label.encode("utf-8")
        for label in labels
    ) + b"\\x00"

    # QU bit requests a unicast response where the responder supports it.
    return (
        struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
        + question_name
        + struct.pack("!HH", 12, 0x8001)
    )


def _discover_mdns_hosts_sync(timeout_seconds: float) -> dict[str, str]:
    """Browse common mDNS service types and return IP-to-hostname mappings."""
    discovered = {}

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            sock.settimeout(0.2)
            sock.bind(("", 0))

            for service_type in MDNS_SERVICE_TYPES:
                try:
                    sock.sendto(
                        build_mdns_ptr_query(service_type),
                        (MDNS_MULTICAST_GROUP, MDNS_PORT),
                    )
                except OSError:
                    logger.debug("Unable to send mDNS query for %s", service_type, exc_info=True)

            deadline = time.monotonic() + max(0.1, timeout_seconds)
            while time.monotonic() < deadline:
                try:
                    packet, _ = sock.recvfrom(9000)
                except socket.timeout:
                    continue
                except OSError:
                    break

                for hostname, addresses in parse_mdns_host_addresses(packet).items():
                    for address in addresses:
                        discovered.setdefault(address, hostname)

    except OSError:
        logger.debug("mDNS discovery is unavailable", exc_info=True)

    return discovered


async def discover_mdns_hosts(
    timeout_seconds: float = MDNS_TIMEOUT_SECONDS,
) -> dict[str, str]:
    """Run bounded mDNS discovery without blocking the event loop."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_discover_mdns_hosts_sync, timeout_seconds),
            timeout=max(0.1, timeout_seconds) + 0.5,
        )
    except Exception:
        logger.debug("mDNS discovery failed", exc_info=True)
        return {}



SSDP_MULTICAST_GROUP = "239.255.255.250"
SSDP_PORT = 1900
SSDP_TIMEOUT_SECONDS = 2.5
SSDP_SEARCH_REQUEST = (
    "M-SEARCH * HTTP/1.1\\r\\n"
    "HOST: 239.255.255.250:1900\\r\\n"
    'MAN: "ssdp:discover"\\r\\n'
    "MX: 2\\r\\n"
    "ST: ssdp:all\\r\\n"
    "\\r\\n"
).encode("ascii")


def parse_ssdp_response(packet: bytes) -> dict[str, str]:
    """Parse useful headers from a successful SSDP discovery response."""
    try:
        lines = packet.decode("iso-8859-1").replace("\\r\\n", "\\n").split("\\n")
        if not lines or not lines[0].upper().startswith("HTTP/1."):
            return {}
        if " 200 " not in lines[0]:
            return {}

        headers = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            key = name.strip().lower()
            if key in {"location", "server", "usn", "st", "nt", "cache-control"}:
                headers[key] = value.strip()

        return headers
    except (UnicodeError, AttributeError):
        return {}


def _discover_ssdp_hosts_sync(timeout_seconds: float) -> dict[str, dict[str, str]]:
    """Discover UPnP/SSDP responders and retain their advertised headers."""
    discovered = {}

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(0.2)
            sock.bind(("", 0))
            sock.sendto(SSDP_SEARCH_REQUEST, (SSDP_MULTICAST_GROUP, SSDP_PORT))

            deadline = time.monotonic() + max(0.1, timeout_seconds)
            while time.monotonic() < deadline:
                try:
                    packet, address = sock.recvfrom(8192)
                except socket.timeout:
                    continue
                except OSError:
                    break

                headers = parse_ssdp_response(packet)
                if headers:
                    discovered.setdefault(address[0], headers)

    except OSError:
        logger.debug("SSDP discovery is unavailable", exc_info=True)

    return discovered


async def discover_ssdp_hosts(
    timeout_seconds: float = SSDP_TIMEOUT_SECONDS,
) -> dict[str, dict[str, str]]:
    """Run bounded SSDP discovery without blocking the event loop."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_discover_ssdp_hosts_sync, timeout_seconds),
            timeout=max(0.1, timeout_seconds) + 0.5,
        )
    except Exception:
        logger.debug("SSDP discovery failed", exc_info=True)
        return {}
