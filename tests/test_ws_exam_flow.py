"""Sınav akışının uçtan uca testleri: gerçek WebSocket sunucusu + sahte saat.

Sahte saat (FakeClock) sayesinde "20 dakika geçti" demek için beklemeyiz; saati ileri alırız.
Sunucunun süre kontrolü (ticker) testlerde 0.05 sn'de bir çalışır.
"""

import json
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from websockets.sync.client import ClientConnection, connect

from server.db.models import Answer, EventLog, Exam, SchoolClass, Submission, User
from server.db.session import get_session
from server.net.ws_server import ConnectedStudent, WsServer
from server.services import grading
from server.services.auth import hash_password
from tests.test_ws_server import wait_until

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
DURATION = timedelta(minutes=20)


class FakeClock:
    """Elle ilerletilen saat. Sunucu thread'i ve test thread'i birlikte kullanır."""

    def __init__(self, start: datetime) -> None:
        self._now = start
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self._now += delta


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_student_connected(self, student: ConnectedStudent) -> None:
        self.events.append(("connected", student.username))

    def on_student_disconnected(self, student: ConnectedStudent) -> None:
        self.events.append(("disconnected", student.username))

    def on_answer_saved(self, student: ConnectedStudent, exam_id: int, answered_count: int) -> None:
        self.events.append(("answer_saved", student.username, exam_id, answered_count))

    def on_submitted(self, username: str, exam_id: int, auto_submitted: bool) -> None:
        self.events.append(("submitted", username, exam_id, auto_submitted))

    def on_exam_finished(self, exam_id: int, reason: str) -> None:
        self.events.append(("exam_finished", exam_id, reason))


class GradingSpy:
    """grading.grade_submission yerine geçer; hangi submission'lar için çağrıldığını kaydeder."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[int] = []
        self.fail = fail

    def __call__(self, submission_id: int) -> None:
        self.calls.append(submission_id)
        if self.fail:
            raise RuntimeError("puanlama patladı")


# ---------------------------------------------------------------------------
# Fixture'lar ve yardımcılar
# ---------------------------------------------------------------------------

@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


@pytest.fixture
def observer() -> RecordingObserver:
    return RecordingObserver()


@pytest.fixture
def grading_spy(monkeypatch: pytest.MonkeyPatch) -> GradingSpy:
    spy = GradingSpy()
    monkeypatch.setattr(grading, "grade_submission", spy)
    return spy


@pytest.fixture
def server(seeded_db, clock: FakeClock, observer: RecordingObserver, grading_spy) -> Iterator[WsServer]:
    srv = WsServer(observer=observer, host="127.0.0.1", port=0, clock=clock, tick_interval=0.05)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def exam_id(seeded_db) -> int:
    with get_session() as session:
        return session.scalar(select(Exam.id))


def open_client(server: WsServer) -> ClientConnection:
    return connect(f"ws://127.0.0.1:{server.port}")


def send(ws: ClientConnection, msg_type: str, payload: dict, msg_id: str = "r1") -> None:
    ws.send(json.dumps({"type": msg_type, "id": msg_id, "payload": payload}))


def recv(ws: ClientConnection, timeout: float = 5) -> dict:
    return json.loads(ws.recv(timeout=timeout))


def recv_type(ws: ClientConnection, msg_type: str, timeout: float = 5) -> dict:
    """msg_type gelene kadar okur (aradaki başka mesajları atlar)."""
    while True:
        message = recv(ws, timeout)
        if message["type"] == msg_type:
            return message


def login(ws: ClientConnection, username: str) -> dict:
    send(ws, "login", {"username": username, "password": username}, "login")
    reply = recv(ws)
    assert reply["type"] == "login_ok", reply
    return reply


def classic_question_ids(exam_id: int) -> list[int]:
    with get_session() as session:
        exam = session.get(Exam, exam_id)
        return [eq.question_id for eq in exam.exam_questions if eq.question.type == "classic"]


def save(ws: ClientConnection, exam_id: int, question_id: int, text: str, msg_id: str = "s1") -> dict:
    send(ws, "save_answer", {"exam_id": exam_id, "question_id": question_id, "text_answer": text}, msg_id)
    return recv(ws)


def submission_ids(exam_id: int) -> list[int]:
    with get_session() as session:
        return sorted(session.scalars(select(Submission.id).where(Submission.exam_id == exam_id)))


def logged_events(event: str) -> list[EventLog]:
    with get_session() as session:
        return list(session.scalars(select(EventLog).where(EventLog.event == event)))


# ---------------------------------------------------------------------------
# Sınavın başlaması ve sınava giriş
# ---------------------------------------------------------------------------

def test_start_exam_sends_exam_start_only_to_its_class(server: WsServer, exam_id: int) -> None:
    with open_client(server) as ws_a, open_client(server) as ws_b:
        login(ws_a, "260101001")   # 1. Öğretim A
        login(ws_b, "260101016")   # 1. Öğretim B
        ends_at = server.start_exam(exam_id)
        assert ends_at == T0 + DURATION

        message = recv(ws_a)
        assert message["type"] == "exam_start"
        assert message["payload"]["exam"]["id"] == exam_id
        assert len(message["payload"]["exam"]["questions"]) == 10
        assert message["payload"]["ends_at"] == "2026-11-05T10:20:00Z"
        assert "is_correct" not in json.dumps(message)

        # B sınıfındaki öğrenciye hiçbir şey gitmemeli: sıradaki mesajı ping'in cevabı olmalı
        send(ws_b, "ping", {}, "p")
        assert recv(ws_b)["type"] == "pong"
    assert len(logged_events("exam_started")) == 1


def test_student_logging_in_after_start_gets_exam(server: WsServer, exam_id: int) -> None:
    server.start_exam(exam_id)
    with open_client(server) as ws:
        login(ws, "260101002")
        message = recv(ws)
        assert message["type"] == "exam_start"
        assert message["payload"]["saved_answers"] == {}


def test_reconnect_resends_saved_answers(server: WsServer, exam_id: int, clock: FakeClock) -> None:
    server.start_exam(exam_id)
    question_id = classic_question_ids(exam_id)[0]
    with open_client(server) as ws:
        login(ws, "260101001")
        recv_type(ws, "exam_start")
        clock.advance(timedelta(minutes=3))
        reply = save(ws, exam_id, question_id, "strlen")
        assert reply["type"] == "save_ok" and reply["id"] == "s1"
        assert reply["payload"] == {"question_id": question_id, "saved_at": "2026-11-05T10:03:00Z"}
    # Bağlantı koptu, öğrenci geri geliyor
    with open_client(server) as ws:
        login(ws, "260101001")
        message = recv_type(ws, "exam_start")
        assert message["payload"]["saved_answers"][str(question_id)]["text_answer"] == "strlen"


def test_answer_saved_observer(server: WsServer, exam_id: int, observer: RecordingObserver) -> None:
    server.start_exam(exam_id)
    q1, q2 = classic_question_ids(exam_id)[:2]
    with open_client(server) as ws:
        login(ws, "260101001")
        recv_type(ws, "exam_start")
        save(ws, exam_id, q1, "a")
        save(ws, exam_id, q1, "b")   # aynı soru: sayı artmaz
        save(ws, exam_id, q2, "c")
    saved = [e for e in observer.events if e[0] == "answer_saved"]
    assert saved == [
        ("answer_saved", "260101001", exam_id, 1),
        ("answer_saved", "260101001", exam_id, 1),
        ("answer_saved", "260101001", exam_id, 2),
    ]


# ---------------------------------------------------------------------------
# Gönderme ve puanlama çağrısı
# ---------------------------------------------------------------------------

def test_submit_then_second_submit_rejected(
    server: WsServer, exam_id: int, grading_spy: GradingSpy, observer: RecordingObserver
) -> None:
    server.start_exam(exam_id)
    with open_client(server) as ws:
        login(ws, "260101001")
        recv_type(ws, "exam_start")
        send(ws, "submit", {"exam_id": exam_id}, "sub1")
        reply = recv(ws)
        assert reply["type"] == "submit_ok" and reply["id"] == "sub1"

        send(ws, "submit", {"exam_id": exam_id}, "sub2")
        reply = recv(ws)
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "ALREADY_SUBMITTED"

        reply = save(ws, exam_id, classic_question_ids(exam_id)[0], "geç")
        assert reply["payload"]["code"] == "ALREADY_SUBMITTED"

    assert wait_until(lambda: grading_spy.calls == submission_ids(exam_id))
    assert ("submitted", "260101001", exam_id, False) in observer.events
    assert len(logged_events("submitted")) == 1


def test_time_up_auto_submits_grades_and_sends_exam_end(
    server: WsServer, exam_id: int, clock: FakeClock,
    grading_spy: GradingSpy, observer: RecordingObserver,
) -> None:
    server.start_exam(exam_id)
    with open_client(server) as ws1, open_client(server) as ws2:
        login(ws1, "260101001")
        login(ws2, "260101002")
        recv_type(ws1, "exam_start")
        recv_type(ws2, "exam_start")
        assert save(ws1, exam_id, classic_question_ids(exam_id)[0], "strlen")["type"] == "save_ok"

        clock.advance(DURATION)  # süre doldu
        for ws in (ws1, ws2):
            message = recv_type(ws, "exam_end")
            assert message["payload"] == {"exam_id": exam_id, "reason": "time_up"}

        # Süre dolduktan sonra gelen kayıt reddedilir ve loglanır
        reply = save(ws1, exam_id, classic_question_ids(exam_id)[0], "geç")
        assert reply["payload"]["code"] == "TIME_UP"
        assert len(logged_events("rejected_late")) == 1

    # Her otomatik gönderilen submission için puanlama çağrılır
    assert wait_until(lambda: sorted(grading_spy.calls) == submission_ids(exam_id))
    assert len(grading_spy.calls) == 2
    assert ("exam_finished", exam_id, "time_up") in observer.events
    assert ("submitted", "260101001", exam_id, True) in observer.events
    assert len(logged_events("auto_submitted")) == 2
    with get_session() as session:
        assert session.get(Exam, exam_id).status == "finished"
        assert session.scalar(select(func.count()).select_from(Answer)) == 1  # cevap korundu


def test_stop_exam_auto_submits_and_grades(
    server: WsServer, exam_id: int, grading_spy: GradingSpy, observer: RecordingObserver
) -> None:
    server.start_exam(exam_id)
    with open_client(server) as ws:
        login(ws, "260101001")
        recv_type(ws, "exam_start")
        server.stop_exam(exam_id)
        message = recv_type(ws, "exam_end")
        assert message["payload"]["reason"] == "instructor_stopped"
    assert wait_until(lambda: grading_spy.calls == submission_ids(exam_id))
    assert ("exam_finished", exam_id, "instructor_stopped") in observer.events
    assert len(logged_events("exam_stopped")) == 1


def test_grading_error_does_not_break_submit_or_exam_end(
    server: WsServer, exam_id: int, grading_spy: GradingSpy, clock: FakeClock
) -> None:
    grading_spy.fail = True
    server.start_exam(exam_id)
    with open_client(server) as ws1, open_client(server) as ws2:
        login(ws1, "260101001")
        login(ws2, "260101002")
        recv_type(ws1, "exam_start")
        recv_type(ws2, "exam_start")
        send(ws1, "submit", {"exam_id": exam_id})
        assert recv(ws1)["type"] == "submit_ok"
        clock.advance(DURATION)
        assert recv_type(ws2, "exam_end")["payload"]["reason"] == "time_up"
    assert wait_until(lambda: len(grading_spy.calls) == 2)


def test_extend_sends_exam_update(server: WsServer, exam_id: int, clock: FakeClock) -> None:
    server.start_exam(exam_id)
    with open_client(server) as ws:
        login(ws, "260101001")
        recv_type(ws, "exam_start")
        clock.advance(timedelta(minutes=15))
        new_end = server.extend_exam(exam_id, 10)
        assert new_end == T0 + DURATION + timedelta(minutes=10)
        message = recv_type(ws, "exam_update")
        assert message["payload"] == {
            "exam_id": exam_id, "ends_at": "2026-11-05T10:30:00Z", "server_now": "2026-11-05T10:15:00Z",
        }
        # Eski bitiş saati geçti ama sınav devam ediyor
        clock.advance(timedelta(minutes=6))
        assert save(ws, exam_id, classic_question_ids(exam_id)[0], "x")["type"] == "save_ok"
    assert len(logged_events("exam_extended")) == 1


def test_instructor_errors_are_raised(server: WsServer, exam_id: int) -> None:
    from server.services.exam_session import ExamSessionError

    with pytest.raises(ExamSessionError):
        server.stop_exam(exam_id)  # başlamamış sınav durdurulamaz


# ---------------------------------------------------------------------------
# Loglar
# ---------------------------------------------------------------------------

def test_login_logout_duplicate_and_focus_logs(server: WsServer, exam_id: int) -> None:
    with open_client(server) as ws:
        send(ws, "login", {"username": "260101001", "password": "yanlis"})
        assert recv(ws)["payload"]["code"] == "INVALID_CREDENTIALS"
    with open_client(server) as old, open_client(server) as new:
        login(old, "260101001")
        login(new, "260101001")
        send(new, "focus_lost", {"exam_id": exam_id, "at": "2026-11-05T10:05:00Z"}, "f1")
        # focus_lost'a cevap gelmez; sıradaki mesaj ping'in cevabıdır
        send(new, "ping", {}, "p1")
        assert recv(new)["id"] == "p1"
    assert wait_until(lambda: len(logged_events("disconnected")) == 1)
    assert len(logged_events("login_failed")) == 1
    assert len(logged_events("login")) == 2
    assert len(logged_events("duplicate_session")) == 1
    focus = logged_events("focus_lost")
    assert len(focus) == 1 and focus[0].exam_id == exam_id


# ---------------------------------------------------------------------------
# Eş zamanlılık
# ---------------------------------------------------------------------------

def _add_students(count: int) -> list[str]:
    """A sınıfına ek öğrenci ekler (seed'de A sınıfında 15 öğrenci var)."""
    usernames = [f"26019{i:04d}" for i in range(count)]
    with get_session() as session:
        class_a = session.scalar(select(SchoolClass).where(SchoolClass.name == "1. Öğretim A"))
        for name in usernames:
            session.add(User(
                username=name, full_name=f"Öğrenci {name}", password_hash=hash_password(name),
                role="student", class_id=class_a.id,
            ))
    return usernames


def test_forty_students_save_at_the_same_time(server: WsServer, exam_id: int) -> None:
    usernames = _add_students(40)
    question_ids = classic_question_ids(exam_id)
    server.start_exam(exam_id)
    barrier = threading.Barrier(len(usernames))
    errors: list[str] = []

    def student(username: str) -> None:
        try:
            with open_client(server) as ws:
                login(ws, username)
                recv_type(ws, "exam_start")
                barrier.wait(timeout=10)  # herkes aynı anda kaydetmeye başlasın
                for n, qid in enumerate(question_ids):
                    reply = save(ws, exam_id, qid, f"cevap {n}", f"s{n}")
                    if reply["type"] != "save_ok":
                        errors.append(f"{username}: {reply}")
        except Exception as exc:  # thread içindeki hatayı teste taşı
            errors.append(f"{username}: {exc!r}")

    threads = [threading.Thread(target=student, args=(u,)) for u in usernames]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(Answer)) == 40 * len(question_ids)
