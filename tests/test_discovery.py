import socket

from server.net.discovery import DiscoveryResponder, _parse_answer, discover_server, get_local_ip


def test_discover_finds_responder() -> None:
    responder = DiscoveryResponder(ws_port=9999, port=0)
    responder.start()
    try:
        result = discover_server(timeout=2, port=responder.port)
    finally:
        responder.stop()
    assert result is not None
    host, ws_port = result
    assert ws_port == 9999
    socket.inet_aton(host)  # geçerli bir IPv4 adresi


def test_discover_returns_none_when_no_server() -> None:
    # Boş bir port bul, kimse dinlemesin
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("", 0))
        free_port = sock.getsockname()[1]
    assert discover_server(timeout=0.5, port=free_port) is None


def test_parse_answer_ignores_foreign_packets() -> None:
    assert _parse_answer(b"rastgele") is None
    assert _parse_answer(b'{"service": "baska", "port": 1}') is None
    assert _parse_answer(b'{"service": "labsinav", "port": 8765}') == 8765


def test_get_local_ip_is_ipv4() -> None:
    socket.inet_aton(get_local_ip())
