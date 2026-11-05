"""ServerClient'ın gerçek WebSocket sunucusuyla testleri (Qt ekransız çalışır)."""

from collections.abc import Iterator

import pytest

from tests.qt_utils import qapp, qt_wait_until  # QT_QPA_PLATFORM'u ayarlar; önce gelmeli

from server.net.ws_server import WsServer
from shared.protocol import ErrorCode, MsgType, SaveAnswerRequest, SubmitRequest
from student_app.net import client as client_module
from student_app.net.client import ConnectionState, ServerClient
from tests.test_ws_exam_flow import (  # noqa: F401 — fixture'lar
    FakeClock,
    classic_question_ids,
    clock,
    exam_id,
    grading_spy,
    observer,
    server,
)


class Recorder:
    """İstemcinin yaydığı tüm sinyalleri sırayla kaydeder."""

    def __init__(self, client: ServerClient) -> None:
        self.events: list[tuple] = []
        for name in ("logged_in", "login_failed", "exam_started", "exam_updated", "exam_ended",
                     "save_confirmed", "submit_confirmed", "connection_changed",
                     "connection_error", "connection_lost"):
            getattr(client, name).connect(lambda *args, n=name: self.events.append((n, *args)))
        client.error_received.connect(lambda *args: self.events.append(("error_received", *args)))
        client.session_replaced.connect(lambda: self.events.append(("session_replaced",)))

    def names(self) -> list[str]:
        return [e[0] for e in self.events]

    def last(self, name: str) -> tuple:
        return [e for e in self.events if e[0] == name][-1]


@pytest.fixture
def make_client() -> Iterator:
    qapp()
    clients: list[ServerClient] = []

    def factory() -> tuple[ServerClient, Recorder]:
        c = ServerClient()
        clients.append(c)
        return c, Recorder(c)

    yield factory
    for c in clients:
        c.close()


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "RECONNECT_DELAYS_SEC", [0.1])
    monkeypatch.setattr(client_module.random, "uniform", lambda a, b: 0)


def test_login_exam_start_and_save(server: WsServer, exam_id: int, make_client) -> None:
    client, rec = make_client()
    client.login("127.0.0.1", server.port, "260101001", "260101001")
    qt_wait_until(lambda: "logged_in" in rec.names())
    assert rec.last("logged_in")[1].username == "260101001"
    assert rec.last("connection_changed")[1] == ConnectionState.CONNECTED

    server.start_exam(exam_id)
    qt_wait_until(lambda: "exam_started" in rec.names())
    start = rec.last("exam_started")[1]
    assert start.exam.id == exam_id
    assert client.clock.now() == start.server_now or client.clock.now() > start.server_now

    question_id = classic_question_ids(exam_id)[0]
    client.request(MsgType.SAVE_ANSWER, SaveAnswerRequest(
        exam_id=exam_id, question_id=question_id, text_answer="cevap"))
    qt_wait_until(lambda: "save_confirmed" in rec.names())
    assert rec.last("save_confirmed")[1].question_id == question_id


def test_wrong_password_emits_login_failed(server: WsServer, make_client) -> None:
    client, rec = make_client()
    client.login("127.0.0.1", server.port, "260101001", "yanlis")
    qt_wait_until(lambda: "login_failed" in rec.names())
    assert "hatalı" in rec.last("login_failed")[1]


def test_unreachable_server_emits_connection_error(make_client) -> None:
    client, rec = make_client()
    client.login("127.0.0.1", 1, "260101001", "260101001")  # 1. portta kimse dinlemiyor
    qt_wait_until(lambda: "connection_error" in rec.names(), timeout=8)


def test_error_reply_carries_request_type(server: WsServer, exam_id: int, make_client) -> None:
    client, rec = make_client()
    client.login("127.0.0.1", server.port, "260101001", "260101001")
    server.start_exam(exam_id)
    qt_wait_until(lambda: "exam_started" in rec.names())
    client.request(MsgType.SUBMIT, SubmitRequest(exam_id=exam_id))
    qt_wait_until(lambda: "submit_confirmed" in rec.names())
    client.request(MsgType.SUBMIT, SubmitRequest(exam_id=exam_id))
    qt_wait_until(lambda: "error_received" in rec.names())
    _, code, _message, request_type = rec.last("error_received")
    assert code == ErrorCode.ALREADY_SUBMITTED and request_type == MsgType.SUBMIT


def test_reconnects_and_logs_in_again_after_server_restart(
    seeded_db, clock: FakeClock, exam_id: int, make_client, grading_spy  # noqa: F811
) -> None:
    first = WsServer(host="127.0.0.1", port=0, clock=clock, tick_interval=0.05)
    first.start()
    port = first.port
    client, rec = make_client()
    client.login("127.0.0.1", port, "260101001", "260101001")
    first.start_exam(exam_id)
    qt_wait_until(lambda: "exam_started" in rec.names())

    first.stop()  # eğitmen uygulaması kapandı
    qt_wait_until(lambda: ("connection_changed", ConnectionState.RECONNECTING) in rec.events)

    second = WsServer(host="127.0.0.1", port=port, clock=clock, tick_interval=0.05)
    second.start()  # tekrar açıldı
    try:
        qt_wait_until(lambda: rec.names().count("exam_started") == 2, timeout=10)
        assert rec.names().count("logged_in") == 2
        assert rec.last("connection_changed")[1] == ConnectionState.CONNECTED
    finally:
        second.stop()


def test_second_login_elsewhere_replaces_first_session(server: WsServer, make_client) -> None:
    first, rec1 = make_client()
    first.login("127.0.0.1", server.port, "260101001", "260101001")
    qt_wait_until(lambda: "logged_in" in rec1.names())
    second, rec2 = make_client()
    second.login("127.0.0.1", server.port, "260101001", "260101001")
    qt_wait_until(lambda: "session_replaced" in rec1.names())
    assert "logged_in" in rec2.names()
    qt_wait_until(lambda: True, timeout=0.5)
    assert ("connection_changed", ConnectionState.RECONNECTING) not in rec1.events  # yarışmaz
