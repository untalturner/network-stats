import asyncio
import platform
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class ProbeResult:
    target: str
    protocol: str
    is_available: bool
    latency_ms: float | None
    packet_loss_percent: float | None
    measured_at: datetime
    error: str | None = None
    status_code: int | None = None


def _result(
    target: str,
    protocol: str,
    started: float,
    is_available: bool,
    error: str | None = None,
    status_code: int | None = None,
) -> ProbeResult:
    latency = (time.perf_counter() - started) * 1000

    return ProbeResult(
        target=target,
        protocol=protocol,
        is_available=is_available,
        latency_ms=round(latency, 3) if is_available else None,
        packet_loss_percent=0.0 if is_available else 100.0,
        measured_at=datetime.now(timezone.utc).replace(tzinfo=None),
        error=error,
        status_code=status_code,
    )


async def probe_icmp(target: str, timeout_seconds: float = 5.0) -> ProbeResult:
    started = time.perf_counter()

    if not target or target.strip() != target:
        return _result(target, "icmp", started, False, "Invalid target")

    system = platform.system()

    if system == "Darwin":
        timeout_ms = max(1, int(timeout_seconds * 1000))
        command = ["ping", "-n", "-c", "1", "-W", str(timeout_ms), target]
    elif system == "Linux":
        timeout = max(1, int(timeout_seconds))
        command = ["ping", "-n", "-c", "1", "-W", str(timeout), target]
    else:
        return _result(
            target, "icmp", started, False,
            f"ICMP probing is unsupported on {system}",
        )

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds + 1,
        )

    except FileNotFoundError:
        return _result(
            target, "icmp", started, False,
            "The system ping command is not installed",
        )
    except asyncio.TimeoutError:
        return _result(target, "icmp", started, False, "ICMP probe timed out")

    output = (stdout + stderr).decode(errors="replace")

    if process.returncode != 0:
        return _result(
            target, "icmp", started, False,
            output.strip() or "ICMP request failed",
        )

    match = re.search(r"time[=<]([\d.]+)\s*ms", output, re.IGNORECASE)
    latency = float(match.group(1)) if match else (
        time.perf_counter() - started
    ) * 1000

    return ProbeResult(
        target=target,
        protocol="icmp",
        is_available=True,
        latency_ms=round(latency, 3),
        packet_loss_percent=0.0,
        measured_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


async def probe_tcp(target: str, timeout_seconds: float = 5.0) -> ProbeResult:
    started = time.perf_counter()

    try:
        parsed = urlsplit(f"//{target}")
        host = parsed.hostname
        port = parsed.port

        if not host or port is None:
            raise ValueError("Expected a host and port, for example example.com:443")

    except ValueError as exc:
        return _result(target, "tcp", started, False, str(exc))

    writer = None

    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_seconds,
        )

        result = _result(target, "tcp", started, True)
        return result

    except asyncio.TimeoutError:
        return _result(target, "tcp", started, False, "TCP connection timed out")
    except OSError as exc:
        return _result(target, "tcp", started, False, str(exc))
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


async def probe_http(
    target: str,
    protocol: str,
    timeout_seconds: float = 5.0,
) -> ProbeResult:
    started = time.perf_counter()

    try:
        parsed = urlsplit(target)

        if protocol == "http" and parsed.scheme != "http":
            raise ValueError("HTTP targets must use the http:// scheme")

        if protocol == "https" and parsed.scheme != "https":
            raise ValueError("HTTPS targets must use the https:// scheme")

        if not parsed.hostname:
            raise ValueError("HTTP target must contain a hostname")

    except ValueError as exc:
        return _result(target, protocol, started, False, str(exc))

    try:
        timeout = httpx.Timeout(timeout_seconds)

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            verify=True,
        ) as client:
            response = await client.get(target)

        available = response.status_code < 400

        return _result(
            target,
            protocol,
            started,
            available,
            None if available else f"HTTP status {response.status_code}",
            response.status_code,
        )

    except httpx.TimeoutException:
        return _result(target, protocol, started, False, "HTTP request timed out")
    except httpx.HTTPError as exc:
        return _result(target, protocol, started, False, str(exc))


async def probe_target(
    target: str,
    protocol: str,
    timeout_seconds: float = 5.0,
) -> ProbeResult:
    """Execute one connectivity probe and return its result."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    if protocol == "icmp":
        return await probe_icmp(target, timeout_seconds)

    if protocol == "tcp":
        return await probe_tcp(target, timeout_seconds)

    if protocol in {"http", "https"}:
        return await probe_http(target, protocol, timeout_seconds)

    raise ValueError(f"Unsupported protocol: {protocol}")
