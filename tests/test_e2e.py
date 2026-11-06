"""Uçtan uca test: gerçek WebSocket sunucusu + gerçek istemciler + GERÇEK puanlama.

test_ws_exam_flow.py puanlamayı sahte (spy) fonksiyonla değiştirir; burada hiçbir şey
taklit edilmez. Senaryo:
    giriş → sınav başlat → cevapla → gönder → puan doğru mu → event_logs yazıldı mı →
    süre sonrası istek reddediliyor mu → otomatik gönderilen de puanlandı mı →
    sonuç servisi doğru özet veriyor mu.

Sadece saat sahtedir (FakeClock): "20 dakika geçti" demek için beklemeyiz, saati ileri alırız.
"""

import asyncio
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from websockets.sync.client import ClientConnection

from scripts import fake_students
from server.db.models import EventLog, Exam, Submission
from server.db.session import get_session
from server.net.ws_server import WsServer
from server.services import results
from tests.test_ws_exam_flow import (
    DURATION,
    T0,
    FakeClock,
    login,
    open_client,
    recv,
    recv_type,
    send,
)
from tests.test_ws_server import wait_until

# Cevap anahtarına ait alan adları — istemciye giden hiçbir mesajda bulunmamalı.
SECRET_FIELDS = ["is_correct", "accepted_answers", "test_cases", "expected_output", "is_hidden"]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


@pytest.fixture
def server(seeded_db, clock: FakeClock) -> Iterator[WsServer]:
    srv = WsServer(host="127.0.0.1", port=0, clock=clock, tick_interval=0.05)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def exam_id(seeded_db) -> int:
    with get_session() as session:
        return session.scalar(select(Exam.id))


def answer_key(exam_id: int) -> dict[int, tuple[str, int | str, int | str]]:
    """Test tarafında doğru/yanlış cevabı hazırlamak için: soru id → (tip, doğru, yanlış).

    mcq için şık id'leri, classic için metin. Bu bilgi SADECE test içinde veri tabanından okunur.
    """
    key = {}
    with get_session() as session:
        exam = session.get(Exam, exam_id)
        for eq in exam.exam_questions:
            question = eq.question
            if question.type == "mcq":
                right = next(o.id for o in question.options if o.is_correct)
                wrong = next(o.id for o in question.options if not o.is_correct)
            else:
                right, wrong = question.accepted_answers[0].answer, "yanlış cevap"
            key[question.id] = (question.type, right, wrong)
    return key


def save(ws: ClientConnection, exam_id: int, question_id: int, qtype: str, value: int | str) -> dict:
    payload: dict = {"exam_id": exam_id, "question_id": question_id}
    payload["selected_option_id" if qtype == "mcq" else "text_answer"] = value
    send(ws, "save_answer", payload, f"s{question_id}")
    return recv(ws)


def shout(text: str) -> str:
    """Klasik cevabı büyük harf + fazla boşluk + sondaki noktayla bozar (normalize kontrolü)."""
    return f"   {text.upper()}  . "


def answer_all(ws: ClientConnection, exam_id: int, plan: dict[int, tuple[str, int | str]]) -> None:
    for question_id, (qtype, value) in plan.items():
        reply = save(ws, exam_id, question_id, qtype, value)
        assert reply["type"] == "save_ok", reply


def score_of(username: str, exam_id: int) -> float | None:
    with get_session() as session:
        submission = session.scalar(
            select(Submission).join(Submission.student)
            .where(Submission.exam_id == exam_id, Submission.student.has(username=username))
        )
        return submission.total_score if submission else None


def submission_of(username: str, exam_id: int) -> Submission:
    with get_session() as session:
        return session.scalar(
            select(Submission)
            .where(Submission.exam_id == exam_id, Submission.student.has(username=username))
        )


def event_names() -> list[str]:
    with get_session() as session:
        return list(session.scalars(select(EventLog.event).order_by(EventLog.id)))


# ---------------------------------------------------------------------------
# Ana senaryo
# ---------------------------------------------------------------------------

def test_full_exam_flow_with_real_grading(
    server: WsServer, exam_id: int, clock: FakeClock, temp_events_log: Path
) -> None:
    key = answer_key(exam_id)
    ids = list(key)
    mcq_ids = [q for q in ids if key[q][0] == "mcq"]
    classic_ids = [q for q in ids if key[q][0] == "classic"]
    assert len(mcq_ids) == 6 and len(classic_ids) == 4  # seed: 10 soru × 10 puan

    # 1) Giriş ve sınav başlatma
    with open_client(server) as full, open_client(server) as half, open_client(server) as late:
        for ws, username in ((full, "260101001"), (half, "260101002"), (late, "260101003")):
            login(ws, username)
        server.start_exam(exam_id)
        for ws in (full, half, late):
            message = recv_type(ws, "exam_start")
            raw = json.dumps(message)
            assert all(secret not in raw for secret in SECRET_FIELDS), "cevap anahtarı sızdı!"
            assert len(message["payload"]["exam"]["questions"]) == 10

        # 2) Cevaplar
        # full: hepsi doğru; klasik cevaplar büyük harf/boşluk/nokta ile → normalize edilip doğru sayılmalı
        answer_all(full, exam_id, {
            q: (key[q][0], shout(key[q][1]) if key[q][0] == "classic" else key[q][1]) for q in ids
        })
        # half: ilk 3 mcq + ilk 2 klasik doğru, kalanlar yanlış → 50 puan
        good = set(mcq_ids[:3] + classic_ids[:2])
        answer_all(half, exam_id, {q: (key[q][0], key[q][1] if q in good else key[q][2]) for q in ids})
        # late: 2 mcq + 1 klasik doğru, 1 yanlış, gerisi boş → göndermeden süre dolacak → 30 puan
        answer_all(late, exam_id, {
            mcq_ids[0]: ("mcq", key[mcq_ids[0]][1]),
            mcq_ids[1]: ("mcq", key[mcq_ids[1]][1]),
            mcq_ids[2]: ("mcq", key[mcq_ids[2]][2]),
            classic_ids[0]: ("classic", key[classic_ids[0]][1]),
        })
        send(late, "focus_lost", {"exam_id": exam_id, "at": T0.isoformat()}, "f1")

        # 3) Gönderim ve gerçek puanlama
        for ws in (full, half):
            send(ws, "submit", {"exam_id": exam_id}, "sub")
            assert recv_type(ws, "submit_ok")["id"] == "sub"
        assert wait_until(lambda: score_of("260101001", exam_id) == 100)
        assert wait_until(lambda: score_of("260101002", exam_id) == 50)

        # 4) Süre doluyor → late otomatik gönderilir, herkese exam_end
        clock.advance(DURATION + DURATION)
        for ws in (full, half, late):
            end = recv_type(ws, "exam_end")
            assert end["payload"] == {"exam_id": exam_id, "reason": "time_up"}
        assert wait_until(lambda: score_of("260101003", exam_id) == 30)
        auto = submission_of("260101003", exam_id)
        assert auto.status == "submitted" and auto.auto_submitted
        assert not submission_of("260101001", exam_id).auto_submitted

        # 5) Süre sonrası kayıt ve gönderim reddedilir
        reply = save(late, exam_id, ids[5], *key[ids[5]][:2])
        assert reply["type"] == "error" and reply["payload"]["code"] == "TIME_UP"
        send(late, "submit", {"exam_id": exam_id}, "late-submit")
        reply = recv_type(late, "error")
        assert reply["id"] == "late-submit" and reply["payload"]["code"] == "TIME_UP"

    # 6) Olay logları: veri tabanı ve logs/events.log (JSON Lines)
    assert wait_until(lambda: event_names().count("disconnected") == 3)
    events = event_names()
    assert events.count("login") == 3
    assert events.count("exam_started") == 1
    assert events.count("submitted") == 2
    assert events.count("auto_submitted") == 1
    assert events.count("focus_lost") == 1
    assert events.count("rejected_late") == 2
    file_events = [json.loads(line)["event"] for line in temp_events_log.read_text("utf-8").splitlines()]
    assert sorted(file_events) == sorted(events)

    # 7) Sonuç servisi
    summary = results.exam_summary(exam_id)
    assert summary.max_score == 100
    assert summary.expected_count == 15        # A sınıfı
    assert summary.participant_count == 3
    assert summary.graded_count == 3
    assert summary.average == pytest.approx(60)
    assert summary.median == 50
    assert (summary.highest, summary.lowest) == (100, 30)

    rows = {row.student_no: row for row in results.student_results(exam_id)}
    assert len(rows) == 15
    assert (rows["260101001"].score, rows["260101001"].correct) == (100, 10)
    assert (rows["260101002"].correct, rows["260101002"].wrong) == (5, 5)
    late_row = rows["260101003"]
    assert (late_row.score, late_row.correct, late_row.wrong, late_row.blank) == (30, 3, 1, 6)
    assert sum(1 for row in rows.values() if row.status == "absent") == 12


# ---------------------------------------------------------------------------
# Yük testi betiğinin küçük bir koşusu
# ---------------------------------------------------------------------------

def test_fake_students_small_run(seeded_db, exam_id: int) -> None:
    """scripts.fake_students gerçek saatli sunucuya karşı hatasız çalışmalı."""
    server = WsServer(host="127.0.0.1", port=0, tick_interval=0.05)
    server.start()
    options = fake_students.Options(
        count=6, min_delay=0.02, max_delay=0.06, early_ratio=1 / 3, reconnect_ratio=1 / 3,
        focus_ratio=0.5, wait_start=10, seed=7,
    )
    stats = fake_students.Stats()
    url = f"ws://127.0.0.1:{server.port}"
    runner = threading.Thread(target=lambda: asyncio.run(fake_students.run(options, url, stats)))
    try:
        runner.start()
        assert wait_until(lambda: len(server.connected_students()) == 6, timeout=10)
        server.start_exam(exam_id)
        assert wait_until(lambda: stats.submitted == 2 and stats.reconnect_ok == 2, timeout=10)
        server.stop_exam(exam_id)
        runner.join(timeout=15)
        assert not runner.is_alive()
    finally:
        server.stop()

    assert stats.failed_students == set(), stats.errors
    assert len(stats.connected) == 6
    assert stats.exam_started == 6
    assert (stats.submitted, stats.auto_submitted) == (2, 4)
    assert stats.saves > 0 and len(stats.save_latencies_ms) == stats.saves
    with get_session() as session:
        submissions = session.scalars(select(Submission).where(Submission.exam_id == exam_id)).all()
    assert len(submissions) == 6
    assert wait_until(lambda: results.exam_summary(exam_id).graded_count == 6)
    assert "YÜK TESTİ ÖZETİ" in fake_students.format_summary(stats, 6)


def test_server_grades_leftover_submissions_on_start(seeded_db, exam_id: int) -> None:
    """Uygulama puanlama bitmeden kapandıysa, açılışta puanlanmamış kâğıtlar puanlanır."""
    from server.services import exam_session
    from server.services.auth import authenticate

    student = authenticate("260101001", "260101001")
    exam_session.start_exam(exam_id, T0)
    exam_session.join_exam(exam_id, student.id, "10.0.0.1", T0)
    exam_session.submit(student.id, exam_id, "10.0.0.1", T0)
    assert score_of("260101001", exam_id) is None  # gönderildi ama puanlanmadı

    server = WsServer(host="127.0.0.1", port=0, clock=lambda: T0)
    server.start()
    try:
        assert wait_until(lambda: score_of("260101001", exam_id) == 0)
    finally:
        server.stop()
