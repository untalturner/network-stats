from unittest.mock import patch

from app.discovery import lookup_hostname, lookup_mac_address


def test_lookup_mac_address_returns_complete_arp_entry(tmp_path):
    arp_file = tmp_path / "arp"
    arp_file.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.50.10    0x1         0x2         aa:bb:cc:dd:ee:ff     *        eth0\n"
    )

    with patch("app.discovery.ARP_TABLE_PATH", str(arp_file)):
        assert lookup_mac_address("192.168.50.10") == "aa:bb:cc:dd:ee:ff"


def test_lookup_mac_address_ignores_incomplete_entries(tmp_path):
    arp_file = tmp_path / "arp"
    arp_file.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.50.10    0x1         0x0         00:00:00:00:00:00     *        eth0\n"
    )

    with patch("app.discovery.ARP_TABLE_PATH", str(arp_file)):
        assert lookup_mac_address("192.168.50.10") is None


def test_lookup_mac_address_returns_none_when_table_unavailable():
    with patch("app.discovery.ARP_TABLE_PATH", "/nonexistent/arp"):
        assert lookup_mac_address("192.168.50.10") is None


def test_lookup_hostname_returns_reverse_dns_name():
    with patch(
        "app.discovery.socket.gethostbyaddr",
        return_value=("router.local", [], ["192.168.50.1"]),
    ):
        assert lookup_hostname("192.168.50.1") == "router.local"


def test_lookup_hostname_returns_none_when_reverse_dns_fails():
    with patch(
        "app.discovery.socket.gethostbyaddr",
        side_effect=OSError("No reverse DNS record"),
    ):
        assert lookup_hostname("192.168.50.1") is None


def test_lookup_mac_address_ignores_malformed_entries(tmp_path):
    arp_file = tmp_path / "arp"
    arp_file.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.50.10    0x1         0x2         invalid-mac            *        eth0\n"
    )

    with patch("app.discovery.ARP_TABLE_PATH", str(arp_file)):
        assert lookup_mac_address("192.168.50.10") is None


def test_lookup_mac_address_does_not_return_another_ip_entry(tmp_path):
    arp_file = tmp_path / "arp"
    arp_file.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.50.11    0x1         0x2         aa:bb:cc:dd:ee:ff     *        eth0\n"
    )

    with patch("app.discovery.ARP_TABLE_PATH", str(arp_file)):
        assert lookup_mac_address("192.168.50.10") is None


def _dns_name(name):
    return b"".join(
        bytes([len(label)]) + label.encode("ascii")
        for label in name.rstrip(".").split(".")
    ) + b"\x00"


def test_parse_mdns_ptr_response_extracts_hostname():
    import struct
    from app.discovery import parse_mdns_ptr_response

    question = _dns_name("1.50.168.192.in-addr.arpa") + struct.pack("!HH", 12, 1)
    answer_name = _dns_name("1.50.168.192.in-addr.arpa")
    target = _dns_name("iphone.local")
    answer = (
        answer_name
        + struct.pack("!HHIH", 12, 1, 120, len(target))
        + target
    )
    packet = (
        struct.pack("!HHHHHH", 0, 0x8400, 1, 1, 0, 0)
        + question
        + answer
    )

    assert parse_mdns_ptr_response(packet) == "iphone.local"


def test_parse_mdns_ptr_response_ignores_non_response_packets():
    from app.discovery import parse_mdns_ptr_response

    assert parse_mdns_ptr_response(b"\\x00" * 12) is None


def test_parse_mdns_ptr_response_handles_malformed_packets():
    from app.discovery import parse_mdns_ptr_response

    assert parse_mdns_ptr_response(b"invalid") is None


def _dns_record(name, record_type, data):
    import struct

    return (
        _dns_name(name)
        + struct.pack("!HHIH", record_type, 1, 120, len(data))
        + data
    )


def test_parse_mdns_host_addresses_correlates_ptr_srv_and_a_records():
    import socket
    import struct
    from app.discovery import parse_mdns_host_addresses

    service = "_http._tcp.local"
    instance = "Living Room._http._tcp.local"
    hostname = "living-room.local"

    ptr = _dns_record(service, 12, _dns_name(instance))
    srv_data = struct.pack("!HHH", 0, 0, 8080) + _dns_name(hostname)
    srv = _dns_record(instance, 33, srv_data)
    address = _dns_record(hostname, 1, socket.inet_aton("192.168.50.42"))

    packet = (
        struct.pack("!HHHHHH", 0, 0x8400, 0, 3, 0, 0)
        + ptr + srv + address
    )

    assert parse_mdns_host_addresses(packet) == {
        hostname: {"192.168.50.42"}
    }


def test_parse_mdns_host_addresses_ignores_non_response_and_malformed_packets():
    from app.discovery import parse_mdns_host_addresses

    assert parse_mdns_host_addresses(b"\x00" * 12) == {}
    assert parse_mdns_host_addresses(b"invalid") == {}


def test_parse_mdns_host_addresses_includes_direct_local_a_records():
    import socket
    import struct
    from app.discovery import parse_mdns_host_addresses

    hostname = "printer.local"
    address = _dns_record(hostname, 1, socket.inet_aton("192.168.50.80"))
    packet = struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0) + address

    assert parse_mdns_host_addresses(packet) == {
        hostname: {"192.168.50.80"}
    }


def test_build_mdns_ptr_query_creates_ptr_question():
    import struct
    from app.discovery import build_mdns_ptr_query

    packet = build_mdns_ptr_query("_http._tcp.local")
    assert struct.unpack_from("!HHHHHH", packet, 0) == (0, 0, 1, 0, 0, 0)
    assert packet.endswith(struct.pack("!HH", 12, 0x8001))


def test_build_mdns_ptr_query_rejects_invalid_service_name():
    import pytest
    from app.discovery import build_mdns_ptr_query

    with pytest.raises(ValueError):
        build_mdns_ptr_query("")


def test_discover_mdns_hosts_returns_empty_when_socket_fails():
    import asyncio
    from unittest.mock import patch
    from app.discovery import discover_mdns_hosts

    with patch(
        "app.discovery._discover_mdns_hosts_sync",
        side_effect=OSError("Multicast unavailable"),
    ):
        assert asyncio.run(discover_mdns_hosts(0.1)) == {}




def test_parse_ssdp_response_extracts_device_headers():
    from app.discovery import parse_ssdp_response

    packet = (
        b"HTTP/1.1 200 OK\\r\\n"
        b"CACHE-CONTROL: max-age=1800\\r\\n"
        b"LOCATION: http://192.168.50.1:1900/rootDesc.xml\\r\\n"
        b"SERVER: Linux/5.10 UPnP/1.0 Router/2.0\\r\\n"
        b"ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\\r\\n"
        b"USN: uuid:router-123::urn:schemas-upnp-org:device:InternetGatewayDevice:1\\r\\n"
        b"\\r\\n"
    )

    result = parse_ssdp_response(packet)

    assert result["location"] == "http://192.168.50.1:1900/rootDesc.xml"
    assert result["server"] == "Linux/5.10 UPnP/1.0 Router/2.0"
    assert result["st"] == "urn:schemas-upnp-org:device:InternetGatewayDevice:1"
    assert result["usn"].startswith("uuid:router-123")


def test_parse_ssdp_response_handles_case_insensitive_headers():
    from app.discovery import parse_ssdp_response

    packet = (
        b"HTTP/1.1 200 OK\\r\\n"
        b"LoCaTiOn: http://192.168.50.20/device.xml\\r\\n"
        b"SeRvEr: Example Device\\r\\n\\r\\n"
    )

    assert parse_ssdp_response(packet) == {
        "location": "http://192.168.50.20/device.xml",
        "server": "Example Device",
    }


def test_parse_ssdp_response_ignores_invalid_or_unsuccessful_packets():
    from app.discovery import parse_ssdp_response

    assert parse_ssdp_response(b"not an HTTP response") == {}
    assert parse_ssdp_response(b"HTTP/1.1 404 Not Found\\r\\n\\r\\n") == {}


def test_discover_ssdp_hosts_returns_empty_when_socket_fails():
    import asyncio
    from unittest.mock import patch
    from app.discovery import discover_ssdp_hosts

    with patch(
        "app.discovery._discover_ssdp_hosts_sync",
        side_effect=OSError("Multicast unavailable"),
    ):
        assert asyncio.run(discover_ssdp_hosts(0.1)) == {}
