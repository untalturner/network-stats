import asyncio

import pytest

from app.discovery import discover_tcp_hosts, validate_network


@pytest.mark.asyncio
async def test_discovers_host_with_open_tcp_port():
    async def handle_client(reader, writer):
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    try:
        results = await discover_tcp_hosts(
            "127.0.0.1/32",
            ports=(port,),
            timeout_seconds=1,
        )

        assert len(results) == 1
        assert results[0].ip_address == "127.0.0.1"
        assert results[0].open_ports == (port,)
        assert results[0].response_time_ms >= 0
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_does_not_discover_host_without_open_scanned_ports():
    server = await asyncio.start_server(
        lambda reader, writer: None,
        "127.0.0.1",
        0,
    )
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    results = await discover_tcp_hosts(
        "127.0.0.1/32",
        ports=(port,),
        timeout_seconds=0.2,
    )

    assert results == []


def test_validate_network_accepts_ipv4_cidr():
    network = validate_network("192.168.1.0/24")

    assert str(network) == "192.168.1.0/24"


@pytest.mark.parametrize(
    "network_cidr",
    [
        "not-a-network",
        "2001:db8::/64",
        "10.0.0.0/23",
    ],
)
def test_validate_network_rejects_invalid_or_oversized_networks(network_cidr):
    with pytest.raises(ValueError):
        validate_network(network_cidr)


@pytest.mark.asyncio
async def test_discovery_rejects_empty_ports():
    with pytest.raises(ValueError, match="At least one TCP port"):
        await discover_tcp_hosts("127.0.0.1/32", ports=())


@pytest.mark.asyncio
async def test_discovery_rejects_invalid_port():
    with pytest.raises(ValueError, match="TCP ports"):
        await discover_tcp_hosts("127.0.0.1/32", ports=(70000,))


@pytest.mark.asyncio
async def test_discovery_rejects_invalid_concurrency():
    with pytest.raises(ValueError, match="max_concurrency"):
        await discover_tcp_hosts("127.0.0.1/32", max_concurrency=101)


@pytest.mark.asyncio
async def test_discovery_rejects_invalid_timeout():
    with pytest.raises(ValueError, match="timeout_seconds"):
        await discover_tcp_hosts("127.0.0.1/32", timeout_seconds=0)
