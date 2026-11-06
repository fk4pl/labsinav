"""Sınav yönetimi: sınav oluşturma/düzenleme/silme/çoğaltma ve canlı panel verisi. (Sahibi: B)

Arayüz (instructor_app/ui/exam_builder.py, live_panel.py) veri tabanına doğrudan dokunmaz;
sadece buradaki fonksiyonları çağırır. Fonksiyonlar ORM nesnesi değil, basit veri sınıfları
(dataclass) döndürür.

Sınavı BAŞLATMA / SÜRE EKLEME / BİTİRME burada değildir: onlar öğrencilere mesaj da
gönderdiği için WsServer.start_exam/extend_exam/stop_exam üzerinden yapılır
(kurallar server/services/exam_session.py'de).

Önemli kurallar:
- Sadece taslak ('draft') sınav düzenlenebilir ve silinebilir.
- Her sınav (bitmiş olsa bile) çoğaltılabilir; kopya her zaman taslaktır.
- Hatalar ExamAdminError ile, kullanıcıya gösterilebilir Türkçe mesajla bildirilir.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from server.db.models import (
    Answer,
    EventLog,
    Exam,
    ExamQuestion,
    Question,
    SchoolClass,
    Submission,
    User,
)
from server.db.session import get_session, write_session
from server.services.event_log import Event
from server.services.question_bank import QuestionRow, list_questions, make_preview, points_error

MAX_TITLE_LENGTH = 200
MAX_DURATION_MINUTES = 600

# Arayüzde gösterilen durum adları
STATUS_LABELS = {"draft": "Taslak", "running": "Devam ediyor", "finished": "Bitti"}


class ExamAdminError(Exception):
    """Sınav yönetimi kuralı ihlal edildi. message: kullanıcıya gösterilebilir Türkçe açıklama."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Veri sınıfları
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassRow:
    id: int
    name: str
    student_count: int


@dataclass
class ExamQuestionDraft:
    """Sınavdaki bir soru: hangi soru ve kaç puan."""

    question_id: int
    points: float


@dataclass
class ExamDraft:
    """Kaydedilmek istenen sınav (yeni veya düzenlenen). Soruların sırası listedeki sıradır."""

    title: str
    class_id: int | None
    duration_minutes: int
    questions: list[ExamQuestionDraft] = field(default_factory=list)


@dataclass(frozen=True)
class ExamRow:
    """Sınav listesindeki bir satır."""

    id: int
    title: str
    class_id: int | None
    class_name: str
    question_count: int
    total_points: float
    duration_minutes: int
    status: str
    started_at: datetime | None
    ends_at: datetime | None


@dataclass(frozen=True)
class ExamQuestionRow:
    """Sınav düzenleme ekranında sağdaki listedeki bir soru."""

    question_id: int
    type: str
    text_preview: str
    category_name: str
    points: float


@dataclass(frozen=True)
class ExamDetail:
    row: ExamRow
    questions: list[ExamQuestionRow]


@dataclass(frozen=True)
class LiveStudentRow:
    """Canlı paneldeki bir öğrencinin veri tabanındaki durumu."""

    user_id: int
    username: str
    full_name: str
    submission_status: str | None  # None: sınava hiç girmedi
    answered_count: int
    last_activity: datetime | None
    focus_lost_count: int
    ip: str | None


@dataclass(frozen=True)
class LiveSnapshot:
    """Canlı panelin açılışta çektiği tam görüntü. Sonrası sinyallerle güncellenir."""

    exam_id: int
    title: str
    class_id: int | None
    class_name: str
    status: str
    ends_at: datetime | None
    question_count: int
    students: list[LiveStudentRow]


# ---------------------------------------------------------------------------
# Sınıflar
# ---------------------------------------------------------------------------

def list_classes() -> list[ClassRow]:
    """Tüm sınıflar ve öğrenci sayıları, ada göre sıralı."""
    query = (
        select(SchoolClass, func.count(User.id))
        .outerjoin(User, (User.class_id == SchoolClass.id) & (User.role == "student"))
        .group_by(SchoolClass.id)
        .order_by(SchoolClass.name)
    )
    with get_session() as session:
        return [ClassRow(c.id, c.name, count) for c, count in session.execute(query)]


# ---------------------------------------------------------------------------
# Sınav okuma
# ---------------------------------------------------------------------------

def list_exams() -> list[ExamRow]:
    """Tüm sınavlar, en yeni en üstte."""
    with get_session() as session:
        exams = session.scalars(_exam_query().order_by(Exam.id.desc()))
        return [_to_row(e) for e in exams]


def list_running_exams() -> list[ExamRow]:
    """Şu an devam eden sınavlar (canlı panel ve kapatma uyarısı için)."""
    with get_session() as session:
        exams = session.scalars(_exam_query().where(Exam.status == "running").order_by(Exam.id))
        return [_to_row(e) for e in exams]


def get_exam(exam_id: int) -> ExamDetail:
    with get_session() as session:
        exam = session.scalar(
            _exam_query()
            .options(
                selectinload(Exam.exam_questions)
                .joinedload(ExamQuestion.question)
                .joinedload(Question.category)
            )
            .where(Exam.id == exam_id)
        )
        if exam is None:
            raise ExamAdminError("Sınav bulunamadı (silinmiş olabilir).")
        questions = [
            ExamQuestionRow(
                question_id=eq.question_id,
                type=eq.question.type,
                text_preview=make_preview(eq.question.text),
                category_name=eq.question.category.name if eq.question.category else "",
                points=eq.points,
            )
            for eq in exam.exam_questions
        ]
        return ExamDetail(_to_row(exam), questions)


def _exam_query():
    return select(Exam).options(joinedload(Exam.school_class), selectinload(Exam.exam_questions))


def _to_row(exam: Exam) -> ExamRow:
    return ExamRow(
        id=exam.id,
        title=exam.title,
        class_id=exam.class_id,
        class_name=exam.school_class.name if exam.school_class else "",
        question_count=len(exam.exam_questions),
        total_points=sum(eq.points for eq in exam.exam_questions),
        duration_minutes=exam.duration_minutes,
        status=exam.status,
        started_at=exam.started_at,
        ends_at=exam.ends_at,
    )


# ---------------------------------------------------------------------------
# Doğrulama
# ---------------------------------------------------------------------------

def validate_exam_draft(draft: ExamDraft) -> list[str]:
    """Taslaktaki hataları Türkçe liste olarak döner (boş liste = sorun yok).

    Veri tabanına bakmayan kontroller burada; sınıf/soru var mı gibi kontroller kaydederken yapılır.
    """
    errors = []
    title = draft.title.strip()
    if not title:
        errors.append("Sınav adı boş olamaz.")
    elif len(title) > MAX_TITLE_LENGTH:
        errors.append(f"Sınav adı en fazla {MAX_TITLE_LENGTH} karakter olabilir.")
    if draft.class_id is None:
        errors.append("Bir sınıf seçin.")
    if not 1 <= draft.duration_minutes <= MAX_DURATION_MINUTES:
        errors.append(f"Süre 1 ile {MAX_DURATION_MINUTES} dakika arasında olmalı.")
    ids = [q.question_id for q in draft.questions]
    if len(ids) != len(set(ids)):
        errors.append("Aynı soru sınava iki kez eklenemez.")
    for number, question in enumerate(draft.questions, start=1):
        error = points_error(question.points)
        if error:
            errors.append(f"{number}. soru: {error}")
            break  # aynı mesajı her soru için tekrarlamayalım
    return errors


def _check_valid(draft: ExamDraft) -> None:
    errors = validate_exam_draft(draft)
    if errors:
        raise ExamAdminError("\n".join(errors))


def _check_references(session: Session, draft: ExamDraft, old_question_ids: set[int]) -> None:
    """Sınıf ve sorular gerçekten var mı? Arşivli soru yeni eklenemez (zaten sınavdaysa kalabilir)."""
    if session.get(SchoolClass, draft.class_id) is None:
        raise ExamAdminError("Seçilen sınıf bulunamadı.")
    for item in draft.questions:
        question = session.get(Question, item.question_id)
        if question is None:
            raise ExamAdminError("Sınavdaki bir soru bulunamadı (silinmiş olabilir).")
        if question.is_archived and item.question_id not in old_question_ids:
            raise ExamAdminError(f"Arşivlenmiş soru sınava eklenemez (soru no {question.id}).")


# ---------------------------------------------------------------------------
# Sınav yazma
# ---------------------------------------------------------------------------

def create_exam(draft: ExamDraft, created_by: int | None) -> int:
    """Yeni taslak sınav oluşturur, id'sini döner."""
    _check_valid(draft)
    with write_session() as session:
        _check_references(session, draft, old_question_ids=set())
        exam = Exam(status="draft", created_by=created_by)
        _apply_draft(exam, draft)
        session.add(exam)
        session.flush()
        return exam.id


def update_exam(exam_id: int, draft: ExamDraft) -> None:
    """Taslak sınavı günceller. Başlamış/bitmiş sınav değiştirilemez."""
    _check_valid(draft)
    with write_session() as session:
        exam = _get_draft(session, exam_id, "düzenlenebilir")
        old_ids = {eq.question_id for eq in exam.exam_questions}
        _check_references(session, draft, old_ids)
        exam.exam_questions.clear()
        session.flush()  # eski satırlar silinsin; aynı (exam_id, question_id) tekrar eklenecek
        _apply_draft(exam, draft)


def delete_exam(exam_id: int) -> None:
    """Taslak sınavı siler. Başlamış/bitmiş sınav silinemez (sonuçları var)."""
    with write_session() as session:
        exam = _get_draft(session, exam_id, "silinebilir")
        session.delete(exam)


def duplicate_exam(exam_id: int) -> int:
    """Sınavın taslak kopyasını oluşturur (bitmiş sınavlar dahil). Yeni id'yi döner."""
    with write_session() as session:
        exam = _get(session, exam_id)
        title = f"{exam.title} (kopya)"[:MAX_TITLE_LENGTH]
        copy = Exam(
            title=title, class_id=exam.class_id, duration_minutes=exam.duration_minutes,
            status="draft", weight_tests=exam.weight_tests,
            weight_complexity=exam.weight_complexity, created_by=exam.created_by,
        )
        copy.exam_questions = [
            ExamQuestion(question_id=eq.question_id, points=eq.points, order_index=eq.order_index)
            for eq in exam.exam_questions
        ]
        session.add(copy)
        session.flush()
        return copy.id


def _apply_draft(exam: Exam, draft: ExamDraft) -> None:
    exam.title = draft.title.strip()
    exam.class_id = draft.class_id
    exam.duration_minutes = draft.duration_minutes
    exam.exam_questions = [
        ExamQuestion(question_id=q.question_id, points=q.points, order_index=i)
        for i, q in enumerate(draft.questions)
    ]


def _get(session: Session, exam_id: int) -> Exam:
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ExamAdminError("Sınav bulunamadı (silinmiş olabilir).")
    return exam


def _get_draft(session: Session, exam_id: int, action: str) -> Exam:
    exam = _get(session, exam_id)
    if exam.status != "draft":
        raise ExamAdminError(f"Sadece taslak sınav {action}. Bu sınavı çoğaltıp kopyasını kullanın.")
    return exam


# ---------------------------------------------------------------------------
# Rastgele soru seçme
# ---------------------------------------------------------------------------

def pick_random_questions(
    category_id: int | None, count: int, exclude_ids: set[int],
    rng: random.Random | None = None,
) -> list[QuestionRow]:
    """Kategoriden (None = tüm kategoriler) rastgele `count` soru seçer.

    Sınavda zaten olan sorular (exclude_ids) ve arşivlenmiş sorular seçilmez.
    Yeterli soru yoksa bulunanların hepsini döner; arayüz kullanıcıyı uyarır.
    rng: testlerde aynı sonucu almak için verilebilir.
    """
    candidates = [q for q in list_questions(category_id=category_id) if q.id not in exclude_ids]
    rng = rng or random.Random()
    return rng.sample(candidates, min(count, len(candidates)))


# ---------------------------------------------------------------------------
# Canlı panel
# ---------------------------------------------------------------------------

def get_live_snapshot(exam_id: int) -> LiveSnapshot:
    """Sınıfın tüm öğrencileri ve bu sınavdaki durumları (bağlantı bilgisi hariç).

    Kimin şu an bağlı olduğunu veri tabanı bilmez; onu arayüz WsServer.connected_students()
    ile ekler.
    """
    with get_session() as session:
        exam = session.scalar(_exam_query().where(Exam.id == exam_id))
        if exam is None:
            raise ExamAdminError("Sınav bulunamadı (silinmiş olabilir).")
        students = session.scalars(
            select(User)
            .where(User.class_id == exam.class_id, User.role == "student")
            .order_by(User.username)
        ).all()
        submissions = _submissions_by_student(session, exam_id)
        focus_counts = _focus_lost_counts(session, exam_id)
        rows = [
            _live_row(student, submissions.get(student.id), focus_counts)
            for student in students
        ]
        return LiveSnapshot(
            exam_id=exam.id, title=exam.title, class_id=exam.class_id,
            class_name=exam.school_class.name if exam.school_class else "",
            status=exam.status, ends_at=exam.ends_at,
            question_count=len(exam.exam_questions), students=rows,
        )


def _submissions_by_student(session: Session, exam_id: int) -> dict[int, Submission]:
    query = (
        select(Submission)
        .options(selectinload(Submission.answers))
        .where(Submission.exam_id == exam_id)
    )
    return {s.student_id: s for s in session.scalars(query)}


def _focus_lost_counts(session: Session, exam_id: int) -> dict[str, int]:
    """Kullanıcı adı → bu sınavda kaç kez pencereden çıktığı (event_logs'tan)."""
    query = (
        select(EventLog.username, func.count(EventLog.id))
        .where(EventLog.exam_id == exam_id, EventLog.event == Event.FOCUS_LOST)
        .group_by(EventLog.username)
    )
    return {username: count for username, count in session.execute(query)}


def _live_row(
    student: User, submission: Submission | None, focus_counts: dict[str, int]
) -> LiveStudentRow:
    answers = submission.answers if submission else []
    last_activity = max((a.updated_at for a in answers), default=None)
    if submission is not None:
        # Hiç cevap vermediyse son etkinlik = sınava giriş, gönderdiyse gönderme anı
        times = [t for t in (last_activity, submission.started_at, submission.submitted_at) if t]
        last_activity = max(times, default=None)
    return LiveStudentRow(
        user_id=student.id,
        username=student.username,
        full_name=student.full_name,
        submission_status=submission.status if submission else None,
        answered_count=sum(1 for a in answers if _is_filled(a)),
        last_activity=last_activity,
        focus_lost_count=focus_counts.get(student.username, 0),
        ip=submission.ip if submission else None,
    )


def _is_filled(answer: Answer) -> bool:
    """Boş olmayan cevap mı? (exam_session'daki sayımla aynı kural)"""
    return (
        answer.selected_option_id is not None
        or bool((answer.text_answer or "").strip())
        or bool((answer.code or "").strip())
    )
