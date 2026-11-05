"""Gerçek WebSocket sunucusunu başlatıp istemci gibi bağlanarak yapılan testler."""

import json
import time
from collections.abc import Callable, Iterator

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from server.net.ws_server import CLOSE_DUPLICATE_SESSION, ConnectedStudent, WsServer


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def on_student_connected(self, student: ConnectedStudent) -> None:
        self.events.append(("connected", student.username))

    def on_student_disconnected(self, student: ConnectedStudent) -> None:
        self.events.append(("disconnected", student.username))


@pytest.fixture
def observer() -> RecordingObserver:
    return RecordingObserver()


@pytest.fixture
def server(seeded_db, observer: RecordingObserver) -> Iterator[WsServer]:
    srv = WsServer(observer=observer, host="127.0.0.1", port=0)  # port 0 = boş bir port seç
    srv.start()
    yield srv
    srv.stop()


def wait_until(condition: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def request(ws: ClientConnection, msg_type: str, payload: dict, msg_id: str = "r1") -> dict:
    ws.send(json.dumps({"type": msg_type, "id": msg_id, "payload": payload}))
    return json.loads(ws.recv(timeout=5))


def login(ws: ClientConnection, username: str, password: str | None = None) -> dict:
    return request(ws, "login", {"username": username, "password": password or username})


def open_client(server: WsServer) -> ClientConnection:
    return connect(f"ws://127.0.0.1:{server.port}")


def test_login_ok(server: WsServer, observer: RecordingObserver) -> None:
    with open_client(server) as ws:
        reply = login(ws, "260101001")
        assert reply["type"] == "login_ok"
        assert reply["id"] == "r1"
        assert reply["payload"]["user"]["full_name"] == "Ahmet Yılmaz"
        assert reply["payload"]["user"]["class_name"] == "1. Öğretim A"
        assert [s.username for s in server.connected_students()] == ["260101001"]
    assert wait_until(lambda: server.connected_students() == [])
    assert observer.events == [("connected", "260101001"), ("disconnected", "260101001")]


def test_two_students_counted(server: WsServer) -> None:
    with open_client(server) as ws1, open_client(server) as ws2:
        assert login(ws1, "260101001")["type"] == "login_ok"
        assert login(ws2, "260101016")["type"] == "login_ok"
        assert len(server.connected_students()) == 2


def test_wrong_password(server: WsServer) -> None:
    with open_client(server) as ws:
        reply = login(ws, "260101001", "yanlis")
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "INVALID_CREDENTIALS"
        assert reply["payload"]["message"] == "Öğrenci numarası veya şifre hatalı."
        assert server.connected_students() == []


def test_instructor_cannot_login_as_student(server: WsServer) -> None:
    with open_client(server) as ws:
        reply = login(ws, "egitmen", "egitmen123")
        assert reply["payload"]["code"] == "NOT_STUDENT"


def test_ping_pong(server: WsServer) -> None:
    with open_client(server) as ws:
        reply = request(ws, "ping", {}, "p1")
        assert reply["type"] == "pong" and reply["id"] == "p1"
        assert "server_now" in reply["payload"]


def test_requires_login(server: WsServer) -> None:
    with open_client(server) as ws:
        reply = request(ws, "submit", {"exam_id": 1})
        assert reply["payload"]["code"] == "NOT_AUTHENTICATED"


def test_unimplemented_type_after_login(server: WsServer) -> None:
    with open_client(server) as ws:
        login(ws, "260101001")
        # Sunucuya gönderilmesi anlamsız bir tip (sunucu -> istemci mesajı)
        reply = request(ws, "pong", {"server_now": "2026-11-05T10:00:00Z"})
        assert reply["payload"]["code"] == "UNKNOWN_TYPE"


def test_bad_json(server: WsServer) -> None:
    with open_client(server) as ws:
        ws.send("bu json değil")
        reply = json.loads(ws.recv(timeout=5))
        assert reply["type"] == "error" and reply["payload"]["code"] == "BAD_REQUEST"
        # Bağlantı açık kalmalı
        assert request(ws, "ping", {})["type"] == "pong"


def test_duplicate_session_closes_old(server: WsServer, observer: RecordingObserver) -> None:
    with open_client(server) as old, open_client(server) as new:
        assert login(old, "260101001")["type"] == "login_ok"
        assert login(new, "260101001")["type"] == "login_ok"
        with pytest.raises(ConnectionClosed):
            old.recv(timeout=5)
        assert old.close_code == CLOSE_DUPLICATE_SESSION
        # Eski bağlantının kapanması yeni oturumu silmemeli
        time.sleep(0.1)
        assert len(server.connected_students()) == 1
