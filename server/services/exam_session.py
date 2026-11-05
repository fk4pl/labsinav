"""Sınav oturumu: sınav başlatma, cevap kaydetme, gönderme, süre kontrolü. (Sahibi: A)

Bu dosya sadece KURALLARI ve veri tabanı işlerini içerir; WebSocket bilmez.
Mesajı kime göndereceğine server/net/ws_server.py karar verir.

Zaman: Her fonksiyon şu anki zamanı `now` parametresiyle alır. Sunucu gerçek saati verir,
testler istedikleri saati verir (böylece "süre doldu" durumu beklemeden test edilir).

Kurallar bozulursa ExamSessionError fırlatılır. İçindeki `message` Türkçedir ve
öğrenciye/eğitmene olduğu gibi gösterilebilir.

Veri tabanına yazan her fonksiyon write_session() kullanır (bkz. server/db/session.py).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from server.db.models import (
    Answer,
    Exam,
    ExamQuestion,
    Question,
    QuestionOption,
    Submission,
    User,
)
from server.db.session import get_session, write_session
from shared.protocol import (
    ErrorCode,
    ExamForStudent,
    ExamStart,
    OptionForStudent,
    QuestionForStudent,
    SaveAnswerRequest,
    SavedAnswer,
)

MAX_EXTEND_MINUTES = 600


class ExamSessionError(Exception):
    """Sınav kuralı ihlal edildi. code: ErrorCode sabiti, message: Türkçe açıklama."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Fonksiyonların döndürdüğü sonuçlar
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExamTiming:
    """Başlatılan / süresi uzatılan sınavın özeti."""

    exam_id: int
    class_id: int
    ends_at: datetime


@dataclass(frozen=True)
class AutoSubmitted:
    submission_id: int
    username: str


@dataclass(frozen=True)
class FinishedExam:
    exam_id: int
    class_id: int
    reason: str  # "time_up" | "instructor_stopped"
    auto_submitted: list[AutoSubmitted]


@dataclass(frozen=True)
class SaveResult:
    question_id: int
    saved_at: datetime
    answered_count: int  # öğrencinin cevapladığı soru sayısı (canlı panel için)


@dataclass(frozen=True)
class SubmitResult:
    submission_id: int
    submitted_at: datetime


# ---------------------------------------------------------------------------
# Eğitmen işlemleri: başlat, uzat, durdur
# ---------------------------------------------------------------------------

def start_exam(exam_id: int, now: datetime) -> ExamTiming:
    """Taslak sınavı başlatır: durum 'running', bitiş = şimdi + süre."""
    with write_session() as session:
        exam = _get_exam(session, exam_id)
        _check_can_start(session, exam)
        exam.status = "running"
        exam.started_at = now
        exam.ends_at = now + timedelta(minutes=exam.duration_minutes)
        return ExamTiming(exam.id, exam.class_id, exam.ends_at)


def extend_exam(exam_id: int, minutes: int, now: datetime) -> ExamTiming:
    """Devam eden sınava süre ekler. Yeni bitiş saatini döner."""
    if not 1 <= minutes <= MAX_EXTEND_MINUTES:
        raise ExamSessionError(
            ErrorCode.BAD_REQUEST, f"Eklenecek süre 1 ile {MAX_EXTEND_MINUTES} dakika arasında olmalı."
        )
    with write_session() as session:
        exam = _get_exam(session, exam_id)
        _check_running(exam, now)
        exam.ends_at = exam.ends_at + timedelta(minutes=minutes)
        return ExamTiming(exam.id, exam.class_id, exam.ends_at)


def stop_exam(exam_id: int, now: datetime) -> FinishedExam:
    """Eğitmen sınavı erken bitirir. Gönderilmemiş cevaplar otomatik gönderilir."""
    with write_session() as session:
        exam = _get_exam(session, exam_id)
        _check_running(exam, now)
        exam.ends_at = now  # gerçek bitiş saati kayıtlarda görünsün
        return _finish_exam(session, exam, "instructor_stopped", now)


def finish_expired_exams(now: datetime) -> list[FinishedExam]:
    """Süresi dolmuş tüm 'running' sınavları bitirir. Sunucu bunu saniyede bir çağırır.

    Uygulama kapalıyken süre dolduysa, açılıştaki ilk çağrıda bitirilir.
    """
    # Önce kilitsiz bak: çoğu zaman bitecek sınav yoktur, boşuna yazma kilidi alınmasın.
    with get_session() as session:
        expired_ids = list(session.scalars(
            select(Exam.id).where(Exam.status == "running", Exam.ends_at <= now)
        ))
    finished = []
    for exam_id in expired_ids:
        with write_session() as session:
            exam = _get_exam(session, exam_id)
            # Kilidi beklerken eğitmen durdurmuş veya süre eklemiş olabilir.
            if exam.status == "running" and exam.ends_at <= now:
                finished.append(_finish_exam(session, exam, "time_up", exam.ends_at))
    return finished


def _finish_exam(session: Session, exam: Exam, reason: str, at: datetime) -> FinishedExam:
    """Gönderilmemiş submission'ları kayıtlı cevaplarla gönderir, sınavı 'finished' yapar."""
    open_submissions = session.scalars(
        select(Submission)
        .options(joinedload(Submission.student))
        .where(Submission.exam_id == exam.id, Submission.status == "in_progress")
    ).all()
    for submission in open_submissions:
        submission.status = "submitted"
        submission.submitted_at = at
        submission.auto_submitted = True
    exam.status = "finished"
    auto = [AutoSubmitted(s.id, s.student.username) for s in open_submissions]
    return FinishedExam(exam.id, exam.class_id, reason, auto)


def _check_can_start(session: Session, exam: Exam) -> None:
    if exam.status != "draft":
        raise ExamSessionError(ErrorCode.BAD_REQUEST, "Sadece taslak durumundaki sınav başlatılabilir.")
    if exam.class_id is None:
        raise ExamSessionError(ErrorCode.BAD_REQUEST, "Sınava bir sınıf atanmamış.")
    if not exam.exam_questions:
        raise ExamSessionError(ErrorCode.BAD_REQUEST, "Sınavda hiç soru yok.")
    if exam.duration_minutes <= 0:
        raise ExamSessionError(ErrorCode.BAD_REQUEST, "Sınav süresi sıfırdan büyük olmalı.")
    other = session.scalar(
        select(Exam).where(Exam.class_id == exam.class_id, Exam.status == "running")
    )
    if other is not None:
        raise ExamSessionError(
            ErrorCode.BAD_REQUEST, f"Bu sınıfta devam eden başka bir sınav var: {other.title}"
        )


def _check_running(exam: Exam, now: datetime) -> None:
    if exam.status != "running" or _is_time_up(exam, now):
        raise ExamSessionError(ErrorCode.EXAM_NOT_ACTIVE, "Bu sınav şu anda devam etmiyor.")


# ---------------------------------------------------------------------------
# Öğrencinin sınava girmesi (ilk giriş ve yeniden bağlanma)
# ---------------------------------------------------------------------------

def find_active_exam_for_student(student_id: int, now: datetime) -> int | None:
    """Öğrencinin şu an girmesi gereken sınavın id'si; yoksa None.

    Şartlar: öğrencinin sınıfında, 'running', süresi dolmamış ve öğrenci henüz göndermemiş.
    """
    with get_session() as session:
        student = session.get(User, student_id)
        if student is None or student.class_id is None:
            return None
        exam = session.scalar(
            select(Exam).where(
                Exam.class_id == student.class_id, Exam.status == "running", Exam.ends_at > now
            )
        )
        if exam is None:
            return None
        submission = _find_submission(session, exam.id, student_id)
        if submission is not None and submission.status == "submitted":
            return None
        return exam.id


def join_exam(exam_id: int, student_id: int, ip: str, now: datetime) -> ExamStart:
    """Öğrenciyi sınava sokar (submission yoksa oluşturur) ve exam_start içeriğini döner."""
    open_submission(exam_id, student_id, ip, now)
    return build_exam_start(exam_id, student_id, now)


def open_submission(exam_id: int, student_id: int, ip: str, now: datetime) -> int:
    """Öğrencinin bu sınavdaki submission'ını döner; yoksa 'in_progress' olarak oluşturur."""
    with write_session() as session:
        return _get_or_create_submission(session, exam_id, student_id, ip, now).id


def build_exam_start(exam_id: int, student_id: int, now: datetime) -> ExamStart:
    """Öğrenciye gidecek sınav içeriği. CEVAP ANAHTARI İÇERMEZ.

    Sadece QuestionForStudent / OptionForStudent kullanılır; bu modellerde is_correct,
    kabul edilen cevaplar ve test case alanları yoktur (protocol.py).
    """
    with get_session() as session:
        exam = session.scalar(
            select(Exam)
            .options(
                selectinload(Exam.exam_questions)
                .joinedload(ExamQuestion.question)
                .options(selectinload(Question.options), joinedload(Question.code_question))
            )
            .where(Exam.id == exam_id)
        )
        if exam is None:
            raise ExamSessionError(ErrorCode.EXAM_NOT_ACTIVE, "Sınav bulunamadı.")
        questions = [_question_for_student(eq) for eq in exam.exam_questions]
        submission = _find_submission(session, exam_id, student_id)
        saved = _saved_answers(session, submission.id) if submission else {}
        return ExamStart(
            exam=ExamForStudent(id=exam.id, title=exam.title, questions=questions),
            ends_at=exam.ends_at, server_now=now, saved_answers=saved,
        )


def _question_for_student(exam_question: ExamQuestion) -> QuestionForStudent:
    question = exam_question.question
    options = []
    if question.type == "mcq":
        options = [
            OptionForStudent(id=o.id, text=o.text, order_index=o.order_index)
            for o in question.options
        ]
    starter_code = None
    if question.type == "code" and question.code_question is not None:
        starter_code = question.code_question.starter_code
    return QuestionForStudent(
        id=question.id, type=question.type, text=question.text,
        points=exam_question.points, order_index=exam_question.order_index,
        options=options, starter_code=starter_code,
    )


def _saved_answers(session: Session, submission_id: int) -> dict[int, SavedAnswer]:
    answers = session.scalars(select(Answer).where(Answer.submission_id == submission_id))
    return {
        a.question_id: SavedAnswer(
            selected_option_id=a.selected_option_id, text_answer=a.text_answer, code=a.code
        )
        for a in answers
    }


# ---------------------------------------------------------------------------
# Öğrenci işlemleri: cevap kaydet, gönder
# ---------------------------------------------------------------------------

def save_answer(student_id: int, request: SaveAnswerRequest, ip: str, now: datetime) -> SaveResult:
    """Cevabı kaydeder (varsa günceller, yoksa ekler)."""
    with write_session() as session:
        exam = _load_exam_for_student(session, request.exam_id, student_id, now)
        submission = _get_or_create_submission(session, exam.id, student_id, ip, now)
        _check_not_submitted(submission)
        question = _get_exam_question(session, exam.id, request.question_id)
        answer = _get_or_create_answer(session, submission.id, question.id)
        _apply_answer(session, answer, question, request)
        answer.updated_at = now
        session.flush()
        return SaveResult(question.id, now, _count_answered(session, submission.id))


def submit(student_id: int, exam_id: int, ip: str, now: datetime) -> SubmitResult:
    """Öğrenci sınavı bitirir. İkinci kez gönderilemez."""
    with write_session() as session:
        exam = _load_exam_for_student(session, exam_id, student_id, now)
        submission = _get_or_create_submission(session, exam.id, student_id, ip, now)
        _check_not_submitted(submission)
        submission.status = "submitted"
        submission.submitted_at = now
        submission.ip = ip
        submission.auto_submitted = False
        session.flush()
        return SubmitResult(submission.id, now)


def _load_exam_for_student(session: Session, exam_id: int, student_id: int, now: datetime) -> Exam:
    """Sınavı getirir; öğrencinin sınavı değilse veya süre dolduysa hata fırlatır."""
    exam = session.get(Exam, exam_id)
    student = session.get(User, student_id)
    if exam is None or student is None or exam.class_id != student.class_id or exam.status == "draft":
        raise ExamSessionError(ErrorCode.EXAM_NOT_ACTIVE, "Bu sınav şu anda aktif değil.")
    if exam.status == "finished" or _is_time_up(exam, now):
        raise ExamSessionError(ErrorCode.TIME_UP, "Sınav süresi doldu; işlem kabul edilmedi.")
    return exam


def _check_not_submitted(submission: Submission) -> None:
    if submission.status == "submitted":
        raise ExamSessionError(ErrorCode.ALREADY_SUBMITTED, "Bu sınavı zaten gönderdiniz.")


def _get_exam_question(session: Session, exam_id: int, question_id: int) -> Question:
    exam_question = session.get(ExamQuestion, (exam_id, question_id))
    if exam_question is None:
        raise ExamSessionError(ErrorCode.BAD_REQUEST, "Bu soru sınavda yok.")
    return exam_question.question


def _apply_answer(
    session: Session, answer: Answer, question: Question, request: SaveAnswerRequest
) -> None:
    """Soru tipine uygun alanı yazar; diğer alanlar yok sayılır."""
    if question.type == "mcq":
        option_id = request.selected_option_id
        if option_id is not None:
            option = session.get(QuestionOption, option_id)
            if option is None or option.question_id != question.id:
                raise ExamSessionError(ErrorCode.BAD_REQUEST, "Geçersiz şık seçildi.")
        answer.selected_option_id = option_id
    elif question.type == "classic":
        answer.text_answer = request.text_answer
    else:
        answer.code = request.code


def _count_answered(session: Session, submission_id: int) -> int:
    """Boş olmayan cevap sayısı (şık seçilmiş veya metin/kod yazılmış)."""
    answers = session.scalars(select(Answer).where(Answer.submission_id == submission_id))
    return sum(1 for a in answers if _is_filled(a))


def _is_filled(answer: Answer) -> bool:
    return (
        answer.selected_option_id is not None
        or bool((answer.text_answer or "").strip())
        or bool((answer.code or "").strip())
    )


# ---------------------------------------------------------------------------
# Küçük yardımcılar
# ---------------------------------------------------------------------------

def _is_time_up(exam: Exam, now: datetime) -> bool:
    return exam.ends_at is not None and now >= exam.ends_at


def _get_exam(session: Session, exam_id: int) -> Exam:
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ExamSessionError(ErrorCode.EXAM_NOT_ACTIVE, "Sınav bulunamadı.")
    return exam


def _find_submission(session: Session, exam_id: int, student_id: int) -> Submission | None:
    return session.scalar(
        select(Submission).where(Submission.exam_id == exam_id, Submission.student_id == student_id)
    )


def _get_or_create_submission(
    session: Session, exam_id: int, student_id: int, ip: str, now: datetime
) -> Submission:
    submission = _find_submission(session, exam_id, student_id)
    if submission is None:
        submission = Submission(exam_id=exam_id, student_id=student_id, ip=ip, started_at=now)
        session.add(submission)
        session.flush()
    return submission


def _get_or_create_answer(session: Session, submission_id: int, question_id: int) -> Answer:
    answer = session.scalar(
        select(Answer).where(Answer.submission_id == submission_id, Answer.question_id == question_id)
    )
    if answer is None:
        answer = Answer(submission_id=submission_id, question_id=question_id)
        session.add(answer)
    return answer
