import asyncio

import pytest

from app.probes import probe_target


@pytest.mark.asyncio
async def test_tcp_probe_succeeds():
    async def handle_client(reader, writer):
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    try:
        result = await probe_target(
            f"127.0.0.1:{port}",
            "tcp",
            timeout_seconds=2,
        )

        assert result.is_available is True
        assert result.latency_ms is not None
        assert result.packet_loss_percent == 0
        assert result.error is None
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_tcp_probe_rejects_invalid_target():
    result = await probe_target("not-a-valid-target", "tcp")

    assert result.is_available is False
    assert result.latency_ms is None
    assert result.packet_loss_percent == 100
    assert result.error is not None


@pytest.mark.asyncio
async def test_tcp_probe_reports_connection_failure():
    server = await asyncio.start_server(
        lambda reader, writer: None,
        "127.0.0.1",
        0,
    )
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    result = await probe_target(
        f"127.0.0.1:{port}",
        "tcp",
        timeout_seconds=1,
    )

    assert result.is_available is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_http_probe_rejects_wrong_scheme():
    result = await probe_target(
        "http://example.com",
        "https",
    )

    assert result.is_available is False
    assert "https://" in result.error


@pytest.mark.asyncio
async def test_unsupported_protocol_is_rejected():
    with pytest.raises(ValueError, match="Unsupported protocol"):
        await probe_target("example.com", "ftp")


@pytest.mark.asyncio
async def test_invalid_timeout_is_rejected():
    with pytest.raises(ValueError, match="timeout_seconds"):
        await probe_target("example.com", "icmp", timeout_seconds=0)
