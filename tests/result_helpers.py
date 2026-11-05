"""Puanlama/sonuç testleri için küçük bir sınav kurar.

Sınav (1. Öğretim A, 15 öğrenci):
  1. soru (mcq, 10 puan):     "2 + 2 = ?"  şıklar: A) 3  B) 4 (doğru)  C) 5
  2. soru (classic, 5 puan):  kabul edilen cevaplar: "İstanbul", "Konstantinopolis"
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from scripts.seed import CLASS_A
from server.db.models import (
    Answer,
    ClassicAcceptedAnswer,
    Exam,
    ExamQuestion,
    Question,
    QuestionOption,
    SchoolClass,
    User,
)
from server.db.session import get_session
from server.services import exam_session
from shared.protocol import SaveAnswerRequest

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
IP = "192.168.1.20"
MCQ_POINTS = 10.0
CLASSIC_POINTS = 5.0


@dataclass
class SmallExam:
    exam_id: int
    mcq_id: int
    classic_id: int
    right_option: int   # "4"
    wrong_option: int   # "3"


def create_small_exam() -> SmallExam:
    """Sınavı oluşturur ve T0'da başlatır."""
    with get_session() as session:
        class_a = session.scalar(select(SchoolClass).where(SchoolClass.name == CLASS_A))
        mcq = Question(type="mcq", text="2 + 2 = ?", default_points=1, options=[
            QuestionOption(text="3", is_correct=False, order_index=0),
            QuestionOption(text="4", is_correct=True, order_index=1),
            QuestionOption(text="5", is_correct=False, order_index=2),
        ])
        classic = Question(type="classic", text="Türkiye'nin en kalabalık şehri?", default_points=1,
                           accepted_answers=[ClassicAcceptedAnswer(answer="İstanbul"),
                                             ClassicAcceptedAnswer(answer="Konstantinopolis")])
        exam = Exam(title="Puanlama Testi", class_id=class_a.id, duration_minutes=30)
        # Puanlar sorunun default_points'inden DEĞİL, exam_questions.points'ten gelmeli
        exam.exam_questions = [
            ExamQuestion(question=mcq, points=MCQ_POINTS, order_index=0),
            ExamQuestion(question=classic, points=CLASSIC_POINTS, order_index=1),
        ]
        session.add(exam)
        session.flush()
        small = SmallExam(exam.id, mcq.id, classic.id, mcq.options[1].id, mcq.options[0].id)
    exam_session.start_exam(small.exam_id, T0)
    return small


def student_id(username: str) -> int:
    with get_session() as session:
        return session.scalar(select(User.id).where(User.username == username))


def take_exam(
    exam: SmallExam, username: str, option_id: int | None = None, text: str | None = None,
    submit: bool = True,
) -> int:
    """Öğrenci cevap verir ve (istenirse) gönderir. submission id'sini döner."""
    sid = student_id(username)
    now = T0 + timedelta(minutes=5)
    if option_id is not None:
        request = SaveAnswerRequest(exam_id=exam.exam_id, question_id=exam.mcq_id, selected_option_id=option_id)
        exam_session.save_answer(sid, request, IP, now)
    if text is not None:
        request = SaveAnswerRequest(exam_id=exam.exam_id, question_id=exam.classic_id, text_answer=text)
        exam_session.save_answer(sid, request, IP, now)
    if submit:
        return exam_session.submit(sid, exam.exam_id, IP, now).submission_id
    return exam_session.open_submission(exam.exam_id, sid, IP, now)


def answer_id(submission_id: int, question_id: int) -> int:
    with get_session() as session:
        return session.scalar(select(Answer.id).where(
            Answer.submission_id == submission_id, Answer.question_id == question_id
        ))
