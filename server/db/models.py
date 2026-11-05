"""Veri tabanı tabloları (SQLAlchemy 2.x ORM).

Şema CLAUDE.md'deki "Veri tabanı şeması" bölümüyle birebir aynıdır.
Değişiklik ekip onayı gerektirir.

Tüm zamanlar UTC olarak saklanır (UTCDateTime). Arayüzde yerel saate çevrilir.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Şu anki zaman, UTC (saat dilimi bilgisiyle)."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite saat dilimi tutmaz. Bu tip yazarken UTC'ye çevirir,
    okurken de değeri 'UTC' etiketiyle geri verir."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Saat dilimi olmayan datetime kaydedilemez; utcnow() kullanın.")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Kullanıcılar ve sınıflar
# ---------------------------------------------------------------------------

class SchoolClass(Base):
    """Öğrenci sınıfı/şubesi (ör. '1. Öğretim A'). 'class' Python'da ayrılmış kelime olduğu için bu ad."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

    students: Mapped[list["User"]] = relationship(back_populates="school_class")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('instructor', 'student')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))

    school_class: Mapped[SchoolClass | None] = relationship(back_populates="students")


# ---------------------------------------------------------------------------
# Soru bankası
# ---------------------------------------------------------------------------

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (CheckConstraint("type IN ('mcq', 'classic', 'code')", name="ck_questions_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    default_points: Mapped[float] = mapped_column(Float, default=10)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    # Geçmiş sınavlarda kullanılmış soru silinmez, arşivlenir.
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    category: Mapped[Category | None] = relationship()
    options: Mapped[list["QuestionOption"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="QuestionOption.order_index"
    )
    accepted_answers: Mapped[list["ClassicAcceptedAnswer"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    code_question: Mapped["CodeQuestion | None"] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="TestCase.order_index"
    )


class QuestionOption(Base):
    __tablename__ = "question_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped[Question] = relationship(back_populates="options")


class ClassicAcceptedAnswer(Base):
    """Klasik soru için kabul edilen cevap (karşılaştırma normalize edilerek yapılır)."""

    __tablename__ = "classic_accepted_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    answer: Mapped[str] = mapped_column(Text)

    question: Mapped[Question] = relationship(back_populates="accepted_answers")


class CodeQuestion(Base):
    """Kod sorusunun ek bilgileri (FİNAL)."""

    __tablename__ = "code_questions"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    starter_code: Mapped[str | None] = mapped_column(Text)
    expected_time_complexity: Mapped[str | None] = mapped_column(String(20))
    expected_space_complexity: Mapped[str | None] = mapped_column(String(20))
    input_generator: Mapped[str | None] = mapped_column(Text)
    sizes_json: Mapped[str | None] = mapped_column(Text)
    time_limit_ms: Mapped[int] = mapped_column(Integer, default=2000)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=64)

    question: Mapped[Question] = relationship(back_populates="code_question")


class TestCase(Base):
    """Kod sorusu test girdisi/çıktısı (FİNAL)."""

    __tablename__ = "test_cases"
    __test__ = False  # pytest bu sınıfı test sınıfı sanmasın

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    input: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped[Question] = relationship(back_populates="test_cases")


# ---------------------------------------------------------------------------
# Sınavlar
# ---------------------------------------------------------------------------

class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'running', 'finished')", name="ck_exams_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    weight_tests: Mapped[float] = mapped_column(Float, default=0.7)
    weight_complexity: Mapped[float] = mapped_column(Float, default=0.3)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    school_class: Mapped[SchoolClass | None] = relationship()
    exam_questions: Mapped[list["ExamQuestion"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", order_by="ExamQuestion.order_index"
    )


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    points: Mapped[float] = mapped_column(Float)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    exam: Mapped[Exam] = relationship(back_populates="exam_questions")
    question: Mapped[Question] = relationship()


class Submission(Base):
    """Bir öğrencinin bir sınavdaki oturumu."""

    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_submissions_exam_student"),
        CheckConstraint("status IN ('in_progress', 'submitted')", name="ck_submissions_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ip: Mapped[str | None] = mapped_column(String(45))
    auto_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    total_score: Mapped[float | None] = mapped_column(Float)

    exam: Mapped[Exam] = relationship()
    student: Mapped[User] = relationship()
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("submission_id", "question_id", name="uq_answers_submission_question"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    selected_option_id: Mapped[int | None] = mapped_column(ForeignKey("question_options.id"))
    text_answer: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    points_awarded: Mapped[float | None] = mapped_column(Float)

    submission: Mapped[Submission] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
    code_results: Mapped[list["CodeResult"]] = relationship(
        back_populates="answer", cascade="all, delete-orphan"
    )


class CodeResult(Base):
    """Kod cevabının derleme/test/karmaşıklık sonucu (FİNAL)."""

    __tablename__ = "code_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"))
    compiled: Mapped[bool] = mapped_column(Boolean, default=False)
    compile_output: Mapped[str | None] = mapped_column(Text)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    time_complexity: Mapped[str | None] = mapped_column(String(20))
    space_complexity: Mapped[str | None] = mapped_column(String(20))
    measurements_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    answer: Mapped[Answer] = relationship(back_populates="code_results")


# ---------------------------------------------------------------------------
# Olay kaydı
# ---------------------------------------------------------------------------

class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    event: Mapped[str] = mapped_column(String(50), index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    exam_id: Mapped[int | None] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String(45))
    detail: Mapped[str | None] = mapped_column(Text)
