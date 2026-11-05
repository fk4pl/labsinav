"""exam_session servis testleri. Zaman `now` parametresiyle verilir; beklemek gerekmez."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from server.db.models import (
    Answer,
    ClassicAcceptedAnswer,
    Exam,
    ExamQuestion,
    Question,
    QuestionOption,
    Submission,
    User,
)
from server.db.session import get_session
from server.services import exam_session
from server.services.exam_session import ExamSessionError
from shared.protocol import ErrorCode, SaveAnswerRequest

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)  # sınavın başladığı an
DURATION = timedelta(minutes=20)                        # seed'deki taslak sınavın süresi
IP = "192.168.1.20"
STUDENT_A = "260101001"  # 1. Öğretim A (sınav bu sınıfa ait)
STUDENT_B = "260101016"  # 1. Öğretim B


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def user_id(username: str) -> int:
    with get_session() as session:
        return session.scalar(select(User.id).where(User.username == username))


def exam_questions(exam_id: int) -> list[Question]:
    with get_session() as session:
        rows = session.scalars(
            select(ExamQuestion).where(ExamQuestion.exam_id == exam_id).order_by(ExamQuestion.order_index)
        ).all()
        return [session.get(Question, r.question_id) for r in rows]


def first_question(exam_id: int, qtype: str) -> Question:
    return next(q for q in exam_questions(exam_id) if q.type == qtype)


def option_ids(question_id: int) -> list[int]:
    with get_session() as session:
        return list(session.scalars(
            select(QuestionOption.id).where(QuestionOption.question_id == question_id)
        ))


def get_submission(exam_id: int, username: str) -> Submission | None:
    with get_session() as session:
        return session.scalar(select(Submission).where(
            Submission.exam_id == exam_id, Submission.student_id == user_id(username)
        ))


def save_text(exam_id: int, username: str, question_id: int, text: str, now: datetime):
    request = SaveAnswerRequest(exam_id=exam_id, question_id=question_id, text_answer=text)
    return exam_session.save_answer(user_id(username), request, IP, now)


@pytest.fixture
def exam_id(seeded_db) -> int:
    """Seed'deki taslak sınav."""
    with get_session() as session:
        return session.scalar(select(Exam.id))


@pytest.fixture
def running_exam(exam_id: int) -> int:
    """T0'da başlatılmış sınav."""
    exam_session.start_exam(exam_id, T0)
    return exam_id


# ---------------------------------------------------------------------------
# Sınavı başlatma
# ---------------------------------------------------------------------------

def test_start_exam_sets_times(exam_id: int) -> None:
    timing = exam_session.start_exam(exam_id, T0)
    assert timing.ends_at == T0 + DURATION
    with get_session() as session:
        exam = session.get(Exam, exam_id)
        assert exam.status == "running"
        assert exam.started_at == T0 and exam.ends_at == T0 + DURATION


def test_cannot_start_twice(running_exam: int) -> None:
    with pytest.raises(ExamSessionError):
        exam_session.start_exam(running_exam, T0)


def test_cannot_start_exam_without_questions(seeded_db) -> None:
    with get_session() as session:
        exam = Exam(title="Boş", class_id=1, duration_minutes=10)
        session.add(exam)
        session.flush()
        empty_id = exam.id
    with pytest.raises(ExamSessionError, match="hiç soru yok"):
        exam_session.start_exam(empty_id, T0)


def test_find_active_exam(running_exam: int) -> None:
    assert exam_session.find_active_exam_for_student(user_id(STUDENT_A), T0) == running_exam
    # Başka sınıftaki öğrencinin aktif sınavı yok
    assert exam_session.find_active_exam_for_student(user_id(STUDENT_B), T0) is None
    # Süre dolduktan sonra yok
    assert exam_session.find_active_exam_for_student(user_id(STUDENT_A), T0 + DURATION) is None


# ---------------------------------------------------------------------------
# exam_start içeriği
# ---------------------------------------------------------------------------

def test_exam_start_questions_in_order(running_exam: int) -> None:
    start = exam_session.join_exam(running_exam, user_id(STUDENT_A), IP, T0)
    assert [q.order_index for q in start.exam.questions] == list(range(10))
    assert [q.id for q in start.exam.questions] == [q.id for q in exam_questions(running_exam)]
    assert start.ends_at == T0 + DURATION
    assert start.server_now == T0


def test_exam_start_does_not_leak_answer_key(running_exam: int) -> None:
    start = exam_session.join_exam(running_exam, user_id(STUDENT_A), IP, T0)
    raw = start.model_dump_json()
    assert "is_correct" not in raw
    assert "accepted" not in raw
    # Klasik soruların kabul edilen cevapları (ör. "strlen") hiçbir alanın değeri olmamalı.
    classic_ids = [q.id for q in start.exam.questions if q.type == "classic"]
    with get_session() as session:
        accepted = set(session.scalars(
            select(ClassicAcceptedAnswer.answer).where(ClassicAcceptedAnswer.question_id.in_(classic_ids))
        ))
    assert accepted, "testte kontrol edilecek cevap olmalı"
    classic_dumps = [q for q in start.model_dump(mode="json")["exam"]["questions"] if q["type"] == "classic"]
    assert accepted.isdisjoint(all_strings(classic_dumps))


def all_strings(value) -> set[str]:
    """JSON verisindeki bütün metin değerleri (iç içe sözlük/listeler dahil)."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(all_strings(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(all_strings(v) for v in value)) if value else set()
    return set()


def test_exam_start_contains_saved_answers(running_exam: int) -> None:
    classic = first_question(running_exam, "classic")
    save_text(running_exam, STUDENT_A, classic.id, "strlen", T0 + timedelta(minutes=1))
    start = exam_session.join_exam(running_exam, user_id(STUDENT_A), IP, T0 + timedelta(minutes=2))
    assert start.saved_answers[classic.id].text_answer == "strlen"


# ---------------------------------------------------------------------------
# Cevap kaydetme
# ---------------------------------------------------------------------------

def test_save_answer_upserts(running_exam: int) -> None:
    classic = first_question(running_exam, "classic")
    save_text(running_exam, STUDENT_A, classic.id, "ilk", T0 + timedelta(minutes=1))
    result = save_text(running_exam, STUDENT_A, classic.id, "ikinci", T0 + timedelta(minutes=2))
    assert result.answered_count == 1
    assert result.saved_at == T0 + timedelta(minutes=2)
    with get_session() as session:
        answers = session.scalars(select(Answer)).all()
        assert len(answers) == 1
        assert answers[0].text_answer == "ikinci"


def test_save_mcq_answer_and_count(running_exam: int) -> None:
    mcq = first_question(running_exam, "mcq")
    classic = first_question(running_exam, "classic")
    request = SaveAnswerRequest(exam_id=running_exam, question_id=mcq.id, selected_option_id=option_ids(mcq.id)[0])
    exam_session.save_answer(user_id(STUDENT_A), request, IP, T0)
    result = save_text(running_exam, STUDENT_A, classic.id, "x", T0)
    assert result.answered_count == 2


def test_save_rejects_option_of_other_question(running_exam: int) -> None:
    mcqs = [q for q in exam_questions(running_exam) if q.type == "mcq"]
    wrong_option = option_ids(mcqs[1].id)[0]
    request = SaveAnswerRequest(exam_id=running_exam, question_id=mcqs[0].id, selected_option_id=wrong_option)
    with pytest.raises(ExamSessionError) as info:
        exam_session.save_answer(user_id(STUDENT_A), request, IP, T0)
    assert info.value.code == ErrorCode.BAD_REQUEST


def test_save_rejects_question_not_in_exam(running_exam: int) -> None:
    with get_session() as session:
        in_exam = {q.id for q in exam_questions(running_exam)}
        outside = session.scalar(select(Question.id).where(Question.id.not_in(in_exam)))
    with pytest.raises(ExamSessionError) as info:
        save_text(running_exam, STUDENT_A, outside, "x", T0)
    assert info.value.code == ErrorCode.BAD_REQUEST


def test_save_rejects_student_of_other_class(running_exam: int) -> None:
    classic = first_question(running_exam, "classic")
    with pytest.raises(ExamSessionError) as info:
        save_text(running_exam, STUDENT_B, classic.id, "x", T0)
    assert info.value.code == ErrorCode.EXAM_NOT_ACTIVE


def test_save_rejected_when_exam_not_started(exam_id: int) -> None:
    classic = first_question(exam_id, "classic")
    with pytest.raises(ExamSessionError) as info:
        save_text(exam_id, STUDENT_A, classic.id, "x", T0)
    assert info.value.code == ErrorCode.EXAM_NOT_ACTIVE


def test_save_rejected_after_time_up(running_exam: int) -> None:
    classic = first_question(running_exam, "classic")
    # Son saniyede kabul edilir
    save_text(running_exam, STUDENT_A, classic.id, "zamanında", T0 + DURATION - timedelta(seconds=1))
    # Süre dolduğu anda ve sonrasında reddedilir
    for late in (T0 + DURATION, T0 + DURATION + timedelta(seconds=5)):
        with pytest.raises(ExamSessionError) as info:
            save_text(running_exam, STUDENT_A, classic.id, "geç", late)
        assert info.value.code == ErrorCode.TIME_UP
    start = exam_session.build_exam_start(running_exam, user_id(STUDENT_A), T0)
    assert start.saved_answers[classic.id].text_answer == "zamanında"


def test_save_rejected_after_submit(running_exam: int) -> None:
    classic = first_question(running_exam, "classic")
    exam_session.submit(user_id(STUDENT_A), running_exam, IP, T0 + timedelta(minutes=5))
    with pytest.raises(ExamSessionError) as info:
        save_text(running_exam, STUDENT_A, classic.id, "x", T0 + timedelta(minutes=6))
    assert info.value.code == ErrorCode.ALREADY_SUBMITTED


# ---------------------------------------------------------------------------
# Gönderme
# ---------------------------------------------------------------------------

def test_submit_records_time_and_ip(running_exam: int) -> None:
    at = T0 + timedelta(minutes=5)
    result = exam_session.submit(user_id(STUDENT_A), running_exam, "10.0.0.7", at)
    assert result.submitted_at == at
    submission = get_submission(running_exam, STUDENT_A)
    assert submission.status == "submitted"
    assert submission.submitted_at == at and submission.ip == "10.0.0.7"
    assert submission.auto_submitted is False


def test_cannot_submit_twice(running_exam: int) -> None:
    exam_session.submit(user_id(STUDENT_A), running_exam, IP, T0 + timedelta(minutes=5))
    with pytest.raises(ExamSessionError) as info:
        exam_session.submit(user_id(STUDENT_A), running_exam, IP, T0 + timedelta(minutes=6))
    assert info.value.code == ErrorCode.ALREADY_SUBMITTED


def test_submit_rejected_after_time_up(running_exam: int) -> None:
    with pytest.raises(ExamSessionError) as info:
        exam_session.submit(user_id(STUDENT_A), running_exam, IP, T0 + DURATION)
    assert info.value.code == ErrorCode.TIME_UP


def test_submitted_student_has_no_active_exam(running_exam: int) -> None:
    exam_session.submit(user_id(STUDENT_A), running_exam, IP, T0 + timedelta(minutes=5))
    assert exam_session.find_active_exam_for_student(user_id(STUDENT_A), T0 + timedelta(minutes=6)) is None


# ---------------------------------------------------------------------------
# Süre dolması, durdurma, uzatma
# ---------------------------------------------------------------------------

def test_auto_submit_when_time_up(running_exam: int) -> None:
    classic = first_question(running_exam, "classic")
    save_text(running_exam, "260101001", classic.id, "strlen", T0 + timedelta(minutes=1))
    exam_session.open_submission(running_exam, user_id("260101002"), IP, T0)
    exam_session.submit(user_id("260101003"), running_exam, IP, T0 + timedelta(minutes=2))

    # Süre dolmadan hiçbir şey olmaz
    assert exam_session.finish_expired_exams(T0 + DURATION - timedelta(seconds=1)) == []

    finished = exam_session.finish_expired_exams(T0 + DURATION + timedelta(seconds=1))
    assert len(finished) == 1
    assert finished[0].reason == "time_up"
    assert sorted(a.username for a in finished[0].auto_submitted) == ["260101001", "260101002"]

    auto = get_submission(running_exam, "260101001")
    assert auto.status == "submitted" and auto.auto_submitted is True
    assert auto.submitted_at == T0 + DURATION  # gönderim zamanı = bitiş saati
    manual = get_submission(running_exam, "260101003")
    assert manual.auto_submitted is False  # kendisi gönderen öğrenciye dokunulmaz
    with get_session() as session:
        assert session.get(Exam, running_exam).status == "finished"
        # Kayıtlı cevap korunur
        assert session.scalar(select(func.count()).select_from(Answer)) == 1
    # İkinci çağrı aynı sınavı tekrar bitirmez
    assert exam_session.finish_expired_exams(T0 + DURATION + timedelta(seconds=2)) == []


def test_exam_expired_while_app_was_closed(running_exam: int) -> None:
    """Uygulama kapalıyken süre dolduysa, açılıştaki ilk kontrolde sınav bitirilir."""
    exam_session.open_submission(running_exam, user_id(STUDENT_A), IP, T0)
    finished = exam_session.finish_expired_exams(T0 + timedelta(hours=3))
    assert [a.username for a in finished[0].auto_submitted] == [STUDENT_A]
    assert get_submission(running_exam, STUDENT_A).submitted_at == T0 + DURATION


def test_running_exam_continues_after_restart(running_exam: int) -> None:
    """Uygulama süre bitmeden yeniden açılırsa sınav devam eder."""
    assert exam_session.finish_expired_exams(T0 + timedelta(minutes=10)) == []
    assert exam_session.find_active_exam_for_student(user_id(STUDENT_A), T0 + timedelta(minutes=10)) == running_exam


def test_stop_exam(running_exam: int) -> None:
    exam_session.open_submission(running_exam, user_id(STUDENT_A), IP, T0)
    stop_at = T0 + timedelta(minutes=5)
    finished = exam_session.stop_exam(running_exam, stop_at)
    assert finished.reason == "instructor_stopped"
    assert [a.username for a in finished.auto_submitted] == [STUDENT_A]
    assert get_submission(running_exam, STUDENT_A).submitted_at == stop_at
    with pytest.raises(ExamSessionError) as info:
        save_text(running_exam, STUDENT_A, first_question(running_exam, "classic").id, "x", stop_at)
    assert info.value.code == ErrorCode.TIME_UP
    with pytest.raises(ExamSessionError):
        exam_session.stop_exam(running_exam, stop_at)  # bitmiş sınav tekrar durdurulamaz


def test_extend_exam(running_exam: int) -> None:
    timing = exam_session.extend_exam(running_exam, 10, T0 + timedelta(minutes=15))
    assert timing.ends_at == T0 + DURATION + timedelta(minutes=10)
    # Eski bitiş saatinde artık kayıt kabul edilir ve sınav bitirilmez
    classic = first_question(running_exam, "classic")
    save_text(running_exam, STUDENT_A, classic.id, "x", T0 + DURATION + timedelta(minutes=1))
    assert exam_session.finish_expired_exams(T0 + DURATION + timedelta(minutes=1)) == []


@pytest.mark.parametrize("minutes", [0, -5, 601])
def test_extend_rejects_invalid_minutes(running_exam: int, minutes: int) -> None:
    with pytest.raises(ExamSessionError):
        exam_session.extend_exam(running_exam, minutes, T0)


def test_cannot_extend_finished_exam(running_exam: int) -> None:
    exam_session.finish_expired_exams(T0 + DURATION)
    with pytest.raises(ExamSessionError):
        exam_session.extend_exam(running_exam, 5, T0 + DURATION)
