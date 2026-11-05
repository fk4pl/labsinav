"""Sonuçlar: sınav özeti, öğrenci listesi, öğrenci detayı ve soru analizi. (Sahibi: D — P4)

Bu dosyadaki fonksiyonlar sadece OKUR (get_session). Puan değiştirmek için grading.py'ye bakın.
Arayüz ORM nesnesi değil, buradaki basit veri sınıflarını (dataclass) alır.

Tanımlar:
- Katılımcı: sınavı göndermiş (status = 'submitted') öğrenci.
- İstatistikler (ortalama, medyan, soru başarı oranı...) sadece PUANLANMIŞ kâğıtlardan
  hesaplanır. Puanlama gönderimden hemen sonra arka planda yapılır; birkaç saniye sürebilir.
- Boş: cevap satırı yok ya da şık seçilmemiş / metin yazılmamış.
- Doğru: is_correct = True (elle verilmiş kısmi puan 'yanlış' sayılır ama puanı korunur).
- Zamanlar UTC döner; arayüz yerel saate çevirir.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from server.db.models import Answer, Exam, ExamQuestion, Question, Submission, User
from server.db.session import get_session
from server.services.grading import MANUAL_TYPES

StudentStatus = Literal["submitted", "in_progress", "absent"]
STATUS_LABELS = {"submitted": "Gönderdi", "in_progress": "Devam ediyor", "absent": "Girmedi"}


class ResultsError(Exception):
    """message: kullanıcıya gösterilebilir Türkçe açıklama."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Veri sınıfları
# ---------------------------------------------------------------------------

@dataclass
class ExamChoice:
    """Sınav seçici kutusundaki bir satır."""

    id: int
    title: str
    class_name: str
    status: str
    started_at: datetime | None


@dataclass
class ExamSummary:
    exam_id: int
    title: str
    class_name: str
    max_score: float            # sınavın tam puanı
    expected_count: int         # sınıftaki öğrenci sayısı
    participant_count: int      # gönderen öğrenci sayısı
    graded_count: int           # puanlanmış kâğıt sayısı
    average: float | None = None
    median: float | None = None
    highest: float | None = None
    lowest: float | None = None
    std_dev: float | None = None


@dataclass
class StudentResultRow:
    submission_id: int | None   # sınava girmeyenlerde None
    student_no: str
    full_name: str
    status: StudentStatus
    score: float | None         # puanlanmamışsa None
    correct: int
    wrong: int
    blank: int
    submitted_at: datetime | None
    auto_submitted: bool


@dataclass
class AnswerDetail:
    """Öğrenci detayındaki bir soru."""

    order: int                  # 1'den başlar
    question_id: int
    question_type: str
    question_text: str
    given: str                  # öğrencinin cevabı ("" = boş)
    expected: str               # doğru cevap(lar)
    max_points: float
    points: float | None
    is_correct: bool | None
    is_blank: bool
    is_manual: bool
    answer_id: int | None       # cevap satırı yoksa None
    can_edit: bool              # puanı elle değiştirilebilir mi


@dataclass
class StudentDetail:
    submission_id: int
    student_no: str
    full_name: str
    exam_title: str
    status: StudentStatus
    score: float | None
    max_score: float
    submitted_at: datetime | None
    auto_submitted: bool
    answers: list[AnswerDetail]


@dataclass
class OptionStat:
    letter: str
    text: str
    is_correct: bool
    count: int


@dataclass
class QuestionStat:
    order: int
    question_id: int
    question_type: str
    text: str
    max_points: float
    correct: int
    wrong: int
    blank: int
    correct_rate: float | None   # 0..1, doğru yapanların oranı
    average_rate: float | None   # 0..1, ortalama puan / tam puan (kısmi puanlar dahil)
    options: list[OptionStat] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sınav listesi ve özet
# ---------------------------------------------------------------------------

def list_exams() -> list[ExamChoice]:
    """Başlamış veya bitmiş sınavlar, en yenisi başta."""
    with get_session() as session:
        exams = session.scalars(
            select(Exam).where(Exam.status != "draft").order_by(Exam.started_at.desc(), Exam.id.desc())
        )
        return [
            ExamChoice(e.id, e.title, _class_name(e), e.status, e.started_at) for e in exams
        ]


def exam_summary(exam_id: int) -> ExamSummary:
    with get_session() as session:
        exam = _get_exam(session, exam_id)
        submissions = _submitted(_load_submissions(session, exam_id))
        scores = [s.total_score for s in submissions if s.total_score is not None]
        summary = ExamSummary(
            exam_id=exam.id,
            title=exam.title,
            class_name=_class_name(exam),
            max_score=_max_score(exam),
            expected_count=len(_class_students(session, exam)),
            participant_count=len(submissions),
            graded_count=len(scores),
        )
        if scores:
            summary.average = statistics.fmean(scores)
            summary.median = statistics.median(scores)
            summary.highest = max(scores)
            summary.lowest = min(scores)
            # Sınıfın tamamına bakıyoruz (örneklem değil) → popülasyon standart sapması
            summary.std_dev = statistics.pstdev(scores)
        return summary


# ---------------------------------------------------------------------------
# Öğrenci listesi ve detay
# ---------------------------------------------------------------------------

def student_results(exam_id: int) -> list[StudentResultRow]:
    """Sınıftaki her öğrenci için bir satır (girmeyenler dahil), öğrenci no sırasıyla."""
    with get_session() as session:
        exam = _get_exam(session, exam_id)
        question_ids = [eq.question_id for eq in exam.exam_questions]
        by_student = {s.student_id: s for s in _load_submissions(session, exam_id)}
        rows = [_row_for_submission(s, question_ids) for s in by_student.values()]
        rows += [
            _absent_row(student) for student in _class_students(session, exam)
            if student.id not in by_student
        ]
        return sorted(rows, key=lambda r: r.student_no)


def _row_for_submission(submission: Submission, question_ids: list[int]) -> StudentResultRow:
    answers = {a.question_id: a for a in submission.answers}
    correct = wrong = blank = 0
    for question_id in question_ids:
        answer = answers.get(question_id)
        if answer is None or is_blank(answer):
            blank += 1
        elif answer.is_correct:
            correct += 1
        else:
            wrong += 1
    return StudentResultRow(
        submission_id=submission.id,
        student_no=submission.student.username,
        full_name=submission.student.full_name,
        status=submission.status,  # type: ignore[arg-type]
        score=submission.total_score,
        correct=correct, wrong=wrong, blank=blank,
        submitted_at=submission.submitted_at,
        auto_submitted=submission.auto_submitted,
    )


def _absent_row(student: User) -> StudentResultRow:
    return StudentResultRow(
        submission_id=None, student_no=student.username, full_name=student.full_name,
        status="absent", score=None, correct=0, wrong=0, blank=0,
        submitted_at=None, auto_submitted=False,
    )


def student_detail(submission_id: int) -> StudentDetail:
    """Bir öğrencinin kâğıdı: her soru, verdiği cevap, doğru cevap, aldığı puan."""
    with get_session() as session:
        submission = session.get(Submission, submission_id)
        if submission is None:
            raise ResultsError("Gönderim bulunamadı.")
        exam = submission.exam
        answers = {a.question_id: a for a in submission.answers}
        details = [
            _answer_detail(i + 1, eq, answers.get(eq.question_id), submission.status)
            for i, eq in enumerate(exam.exam_questions)
        ]
        return StudentDetail(
            submission_id=submission.id,
            student_no=submission.student.username,
            full_name=submission.student.full_name,
            exam_title=exam.title,
            status=submission.status,  # type: ignore[arg-type]
            score=submission.total_score,
            max_score=_max_score(exam),
            submitted_at=submission.submitted_at,
            auto_submitted=submission.auto_submitted,
            answers=details,
        )


def _answer_detail(
    order: int, exam_question: ExamQuestion, answer: Answer | None, status: str
) -> AnswerDetail:
    question = exam_question.question
    return AnswerDetail(
        order=order,
        question_id=question.id,
        question_type=question.type,
        question_text=question.text,
        given=_given_text(question, answer),
        expected=_expected_text(question),
        max_points=exam_question.points,
        points=answer.points_awarded if answer else None,
        is_correct=answer.is_correct if answer else None,
        is_blank=answer is None or is_blank(answer),
        is_manual=bool(answer and answer.is_manual),
        answer_id=answer.id if answer else None,
        can_edit=answer is not None and status == "submitted" and question.type in MANUAL_TYPES,
    )


def _given_text(question: Question, answer: Answer | None) -> str:
    if answer is None:
        return ""
    if question.type == "mcq":
        for index, option in enumerate(question.options):
            if option.id == answer.selected_option_id:
                return f"{option_letter(index)}) {option.text}"
        return ""
    if question.type == "classic":
        return (answer.text_answer or "").strip()
    return answer.code or ""


def _expected_text(question: Question) -> str:
    if question.type == "mcq":
        return " / ".join(
            f"{option_letter(i)}) {o.text}" for i, o in enumerate(question.options) if o.is_correct
        )
    if question.type == "classic":
        return " / ".join(a.answer for a in question.accepted_answers)
    return "Test case'lerle değerlendirilir (FİNAL)"


# ---------------------------------------------------------------------------
# Soru analizi
# ---------------------------------------------------------------------------

def question_stats(exam_id: int) -> list[QuestionStat]:
    """Her sorunun doğru yapılma oranı; test sorularında şıkların kaç kez seçildiği.

    Sadece puanlanmış kâğıtlar hesaba katılır.
    """
    with get_session() as session:
        exam = _get_exam(session, exam_id)
        graded = [s for s in _submitted(_load_submissions(session, exam_id)) if s.total_score is not None]
        answer_maps = [{a.question_id: a for a in s.answers} for s in graded]
        return [
            _question_stat(i + 1, eq, [m.get(eq.question_id) for m in answer_maps])
            for i, eq in enumerate(exam.exam_questions)
        ]


def _question_stat(order: int, exam_question: ExamQuestion, answers: list[Answer | None]) -> QuestionStat:
    question = exam_question.question
    filled = [a for a in answers if a is not None and not is_blank(a)]
    correct = sum(1 for a in filled if a.is_correct)
    count = len(answers)
    total_points = sum(a.points_awarded or 0.0 for a in filled)
    full = exam_question.points
    return QuestionStat(
        order=order,
        question_id=question.id,
        question_type=question.type,
        text=question.text,
        max_points=full,
        correct=correct,
        wrong=len(filled) - correct,
        blank=count - len(filled),
        correct_rate=correct / count if count else None,
        average_rate=total_points / (full * count) if count and full > 0 else None,
        options=_option_stats(question, filled) if question.type == "mcq" else [],
    )


def _option_stats(question: Question, answers: list[Answer]) -> list[OptionStat]:
    return [
        OptionStat(
            letter=option_letter(i),
            text=option.text,
            is_correct=option.is_correct,
            count=sum(1 for a in answers if a.selected_option_id == option.id),
        )
        for i, option in enumerate(question.options)
    ]


# ---------------------------------------------------------------------------
# Küçük yardımcılar
# ---------------------------------------------------------------------------

def is_blank(answer: Answer) -> bool:
    """Öğrenci bu soruya hiçbir şey yazmamış / seçmemiş mi?"""
    return (
        answer.selected_option_id is None
        and not (answer.text_answer or "").strip()
        and not (answer.code or "").strip()
    )


def option_letter(index: int) -> str:
    """0 → 'A', 1 → 'B', ..."""
    return chr(ord("A") + index)


def _get_exam(session: Session, exam_id: int) -> Exam:
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ResultsError("Sınav bulunamadı.")
    return exam


def _class_name(exam: Exam) -> str:
    return exam.school_class.name if exam.school_class else "—"


def _max_score(exam: Exam) -> float:
    return sum(eq.points for eq in exam.exam_questions)


def _class_students(session: Session, exam: Exam) -> list[User]:
    if exam.class_id is None:
        return []
    return list(session.scalars(
        select(User).where(User.class_id == exam.class_id, User.role == "student")
    ))


def _load_submissions(session: Session, exam_id: int) -> list[Submission]:
    """Sınavın tüm kâğıtları; cevaplar ve öğrenci tek seferde yüklenir (az sorgu)."""
    return list(session.scalars(
        select(Submission)
        .where(Submission.exam_id == exam_id)
        .options(selectinload(Submission.answers), selectinload(Submission.student))
    ))


def _submitted(submissions: list[Submission]) -> list[Submission]:
    return [s for s in submissions if s.status == "submitted"]
