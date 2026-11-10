"""Öğrenci: son bağlanılan sunucuyu hatırlama ve otomatik bulma başarısızsa onu deneme."""

from tests.qt_utils import qapp, qt_wait_until  # önce gelmeli (offscreen)

import socket
from pathlib import Path

import pytest

from shared.protocol import UserInfo
from student_app import main as student_main
from student_app.demo import DemoBackend
from student_app.last_server import is_reachable, load_last_server, save_last_server
from student_app.main import DiscoveryThread, StudentWindow


def test_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "alt" / "last_server.json"
    assert load_last_server(path) is None
    save_last_server(path, "192.168.1.20", 8765)
    assert load_last_server(path) == ("192.168.1.20", 8765)


def test_broken_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "last_server.json"
    for content in ("bozuk{", '{"host": "x"}', '{"host": "x", "port": 99999}', "[]"):
        path.write_text(content, encoding="utf-8")
        assert load_last_server(path) is None


@pytest.fixture
def listening_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield server.getsockname()[1]


def test_is_reachable(listening_port: int) -> None:
    assert is_reachable("127.0.0.1", listening_port)
    with socket.socket() as probe:  # boş bir port bul
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    assert not is_reachable("127.0.0.1", closed_port, timeout=0.5)


def _run_thread(thread: DiscoveryThread) -> tuple[str, int] | None:
    results: list[object] = []
    thread.finished_with_result.connect(results.append)
    thread.start()
    qt_wait_until(lambda: bool(results))
    thread.wait()
    return results[0]


def test_discovery_falls_back_to_last_server(monkeypatch: pytest.MonkeyPatch, listening_port: int) -> None:
    qapp()
    monkeypatch.setattr(student_main, "discover_server", lambda: None)
    assert _run_thread(DiscoveryThread(("127.0.0.1", listening_port))) == ("127.0.0.1", listening_port)
    assert _run_thread(DiscoveryThread(None)) is None


def test_discovery_prefers_broadcast_result(monkeypatch: pytest.MonkeyPatch) -> None:
    qapp()
    monkeypatch.setattr(student_main, "discover_server", lambda: ("10.0.0.5", 8765))
    monkeypatch.setattr(student_main, "is_reachable", lambda *a: pytest.fail("denenmemeli"))
    assert _run_thread(DiscoveryThread(("192.168.1.20", 8765))) == ("10.0.0.5", 8765)


def test_window_prefills_and_saves_last_server(tmp_path: Path) -> None:
    qapp()
    path = tmp_path / "last_server.json"
    save_last_server(path, "192.168.1.20", 8765)
    window = StudentWindow(DemoBackend(30), last_server_path=path)
    assert window.login_page.address_input.text() == "192.168.1.20"

    window._on_login_requested("10.0.0.7", 9000, "260101001", "260101001")
    window._on_logged_in(UserInfo(id=1, username="260101001", full_name="A B", class_name="A"))
    assert load_last_server(path) == ("10.0.0.7", 9000)
