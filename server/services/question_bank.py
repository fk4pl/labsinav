"""Soru bankası servisleri: soru ve kategori ekleme, düzenleme, silme/arşivleme. (Sahibi: B)

Arayüz (instructor_app/ui/question_bank.py) veri tabanına doğrudan dokunmaz; sadece
buradaki fonksiyonları çağırır. Fonksiyonlar ORM nesnesi değil, basit veri sınıfları
(dataclass) döndürür; böylece arayüz oturum (session) kapandıktan sonra da güvenle okur.

Önemli kurallar:
- Bir sınavda kullanılmış soru silinmez, arşivlenir (eski sonuçlar bozulmasın).
- Başlamış/bitmiş bir sınavda kullanılmış soru DÜZENLENEMEZ: şıkları değiştirmek öğrencilerin
  kayıtlı cevaplarını (answers.selected_option_id) ve puanlarını bozar. Kopyası düzenlenmeli.
- Hatalar QuestionBankError ile, kullanıcıya gösterilebilir Türkçe mesajla bildirilir.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from server.db.models import (
    Category,
    ClassicAcceptedAnswer,
    Exam,
    ExamQuestion,
    Question,
    QuestionOption,
    utcnow,
)
from server.db.session import get_session, write_session
from shared.protocol import OptionForStudent, QuestionForStudent

MIN_OPTIONS = 2
MAX_OPTIONS = 6
PREVIEW_LENGTH = 80
MAX_POINTS = 1000
MAX_CATEGORY_NAME = 100

# Arayüzde gösterilen tür adları
TYPE_LABELS = {"mcq": "Test", "classic": "Klasik", "code": "Kod"}


class QuestionBankError(Exception):
    """Soru bankası kuralı ihlal edildi. message: kullanıcıya gösterilebilir Türkçe açıklama."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Veri sınıfları
# ---------------------------------------------------------------------------

@dataclass
class OptionDraft:
    """Düzenleme diyaloğundaki bir şık."""

    text: str
    is_correct: bool = False


@dataclass
class QuestionDraft:
    """Kaydedilmek istenen soru (yeni veya düzenlenen)."""

    type: str
    text: str
    category_id: int | None
    default_points: float
    options: list[OptionDraft] = field(default_factory=list)        # sadece mcq
    accepted_answers: list[str] = field(default_factory=list)       # sadece classic


@dataclass(frozen=True)
class QuestionRow:
    """Soru tablosundaki bir satır."""

    id: int
    type: str
    category_id: int | None
    category_name: str
    text: str           # tam metin (arayüzdeki arama bunun içinde yapılır)
    text_preview: str   # tabloda gösterilen ilk 80 karakter
    default_points: float
    updated_at: datetime
    is_archived: bool


@dataclass(frozen=True)
class QuestionDetail:
    """Düzenleme diyaloğunu doldurmak için sorunun tamamı."""

    id: int
    draft: QuestionDraft
    is_archived: bool
    used_in_started_exam: bool  # True ise düzenlenemez


@dataclass(frozen=True)
class CategoryRow:
    id: int
    name: str
    question_count: int


# ---------------------------------------------------------------------------
# Doğrulama
# ---------------------------------------------------------------------------

def validate_draft(draft: QuestionDraft) -> list[str]:
    """Sorudaki hataları Türkçe bir liste olarak döner. Liste boşsa soru geçerlidir."""
    errors: list[str] = []
    if not draft.text.strip():
        errors.append("Soru metni boş olamaz.")
    if not 0 < draft.default_points <= MAX_POINTS:
        errors.append(f"Puan 0'dan büyük ve en fazla {MAX_POINTS} olmalı.")

    if draft.type == "mcq":
        errors.extend(_validate_options(draft.options))
    elif draft.type == "classic":
        if not _clean_answers(draft.accepted_answers):
            errors.append("En az bir kabul edilen cevap girin.")
    elif draft.type == "code":
        errors.append("Kod soruları Final'de eklenecek.")
    else:
        errors.append("Geçersiz soru türü.")
    return errors


def _validate_options(options: list[OptionDraft]) -> list[str]:
    errors: list[str] = []
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        errors.append(f"Test sorusunda {MIN_OPTIONS} ile {MAX_OPTIONS} arasında şık olmalı.")
    texts = [o.text.strip() for o in options]
    if any(not t for t in texts):
        errors.append("Boş şık bırakılamaz.")
    filled = [t for t in texts if t]
    if len(set(filled)) != len(filled):
        errors.append("Aynı metne sahip iki şık olamaz.")
    correct_count = sum(1 for o in options if o.is_correct)
    if correct_count != 1:
        errors.append("Tam olarak bir doğru şık işaretleyin.")
    return errors


def _clean_answers(answers: list[str]) -> list[str]:
    """Boşları atar, baş/son boşlukları temizler, tekrarları siler (sıra korunur)."""
    cleaned: list[str] = []
    for answer in answers:
        answer = answer.strip()
        if answer and answer not in cleaned:
            cleaned.append(answer)
    return cleaned


def _check_valid(draft: QuestionDraft) -> None:
    errors = validate_draft(draft)
    if errors:
        raise QuestionBankError("\n".join(errors))


# ---------------------------------------------------------------------------
# Soru okuma
# ---------------------------------------------------------------------------

def list_questions(
    category_id: int | None = None,
    question_type: str | None = None,
    search: str = "",
    include_archived: bool = False,
) -> list[QuestionRow]:
    """Filtrelere uyan sorular, en yeni düzenlenen en üstte."""
    query = select(Question).options(selectinload(Question.category))
    if category_id is not None:
        query = query.where(Question.category_id == category_id)
    if question_type is not None:
        query = query.where(Question.type == question_type)
    if search.strip():
        query = query.where(Question.text.ilike(f"%{search.strip()}%"))
    if not include_archived:
        query = query.where(Question.is_archived.is_(False))
    query = query.order_by(Question.updated_at.desc(), Question.id.desc())

    with get_session() as session:
        return [_to_row(q) for q in session.scalars(query)]


def _to_row(question: Question) -> QuestionRow:
    return QuestionRow(
        id=question.id,
        type=question.type,
        category_id=question.category_id,
        category_name=question.category.name if question.category else "",
        text=question.text,
        text_preview=make_preview(question.text),
        default_points=question.default_points,
        updated_at=question.updated_at,
        is_archived=question.is_archived,
    )


def make_preview(text: str, length: int = PREVIEW_LENGTH) -> str:
    """Metni tek satıra indirir ve ilk `length` karakterini verir."""
    single_line = " ".join(text.split())
    if len(single_line) <= length:
        return single_line
    return single_line[:length].rstrip() + "…"


def get_question(question_id: int) -> QuestionDetail:
    with get_session() as session:
        question = _get(session, question_id)
        draft = QuestionDraft(
            type=question.type,
            text=question.text,
            category_id=question.category_id,
            default_points=question.default_points,
            options=[OptionDraft(o.text, o.is_correct) for o in question.options],
            accepted_answers=[a.answer for a in question.accepted_answers],
        )
        return QuestionDetail(
            id=question.id,
            draft=draft,
            is_archived=question.is_archived,
            used_in_started_exam=_is_used_in_started_exam(session, question_id),
        )


def preview_question(question_id: int) -> QuestionForStudent:
    """Öğrencinin göreceği hâli. Protokoldeki model kullanılır; cevap anahtarı içermez."""
    with get_session() as session:
        question = _get(session, question_id)
        options = [
            OptionForStudent(id=o.id, text=o.text, order_index=o.order_index)
            for o in question.options
        ] if question.type == "mcq" else []
        return QuestionForStudent(
            id=question.id, type=question.type, text=question.text,
            points=question.default_points, order_index=0, options=options,
        )


def _get(session: Session, question_id: int) -> Question:
    question = session.get(Question, question_id)
    if question is None:
        raise QuestionBankError("Soru bulunamadı (silinmiş olabilir).")
    return question


def _is_used_in_any_exam(session: Session, question_id: int) -> bool:
    query = select(ExamQuestion.exam_id).where(ExamQuestion.question_id == question_id).limit(1)
    return session.scalar(query) is not None


def _is_used_in_started_exam(session: Session, question_id: int) -> bool:
    """Soru, 'running' veya 'finished' durumundaki bir sınavda var mı?"""
    query = (
        select(Exam.id)
        .join(ExamQuestion, ExamQuestion.exam_id == Exam.id)
        .where(ExamQuestion.question_id == question_id, Exam.status != "draft")
        .limit(1)
    )
    return session.scalar(query) is not None


# ---------------------------------------------------------------------------
# Soru yazma
# ---------------------------------------------------------------------------

def create_question(draft: QuestionDraft) -> int:
    """Yeni soru ekler, id'sini döner."""
    _check_valid(draft)
    with write_session() as session:
        _check_category_exists(session, draft.category_id)
        question = Question()
        _apply_draft(question, draft)
        session.add(question)
        session.flush()  # id oluşsun
        return question.id


def update_question(question_id: int, draft: QuestionDraft) -> None:
    """Var olan soruyu günceller. Başlamış bir sınavda kullanıldıysa reddeder."""
    _check_valid(draft)
    with write_session() as session:
        question = _get(session, question_id)
        if _is_used_in_started_exam(session, question_id):
            raise QuestionBankError(
                "Bu soru yapılmış bir sınavda kullanıldı; eski sonuçlar bozulmasın diye "
                "değiştirilemez. Soruyu çoğaltıp kopyasını düzenleyin."
            )
        _check_category_exists(session, draft.category_id)
        _apply_draft(question, draft)
        # Sadece şıklar değişse bile "son düzenleme" güncellensin
        question.updated_at = utcnow()


def _apply_draft(question: Question, draft: QuestionDraft) -> None:
    """Taslaktaki bilgileri ORM nesnesine yazar. Eski şıklar/cevaplar tamamen değiştirilir."""
    question.type = draft.type
    question.text = draft.text.strip("\n")
    question.category_id = draft.category_id
    question.default_points = draft.default_points
    if draft.type == "mcq":
        question.options = [
            QuestionOption(text=o.text.strip(), is_correct=o.is_correct, order_index=i)
            for i, o in enumerate(draft.options)
        ]
        question.accepted_answers = []
    else:
        question.options = []
        question.accepted_answers = [
            ClassicAcceptedAnswer(answer=a) for a in _clean_answers(draft.accepted_answers)
        ]


def delete_question(question_id: int) -> Literal["deleted", "archived"]:
    """Hiçbir sınavda kullanılmadıysa siler; kullanıldıysa arşivler. Ne yapıldığını döner."""
    with write_session() as session:
        question = _get(session, question_id)
        if _is_used_in_any_exam(session, question_id):
            question.is_archived = True
            return "archived"
        session.delete(question)
        return "deleted"


def restore_question(question_id: int) -> None:
    """Arşivlenmiş soruyu tekrar kullanılabilir yapar."""
    with write_session() as session:
        _get(session, question_id).is_archived = False


def duplicate_question(question_id: int) -> int:
    """Sorunun (şıkları ve kabul edilen cevaplarıyla) kopyasını oluşturur, yeni id'yi döner."""
    with write_session() as session:
        original = _get(session, question_id)
        copy = Question(
            type=original.type,
            text=original.text,
            category_id=original.category_id,
            default_points=original.default_points,
            options=[
                QuestionOption(text=o.text, is_correct=o.is_correct, order_index=o.order_index)
                for o in original.options
            ],
            accepted_answers=[ClassicAcceptedAnswer(answer=a.answer) for a in original.accepted_answers],
        )
        session.add(copy)
        session.flush()
        return copy.id


# ---------------------------------------------------------------------------
# Kategoriler
# ---------------------------------------------------------------------------

def list_categories() -> list[CategoryRow]:
    """Tüm kategoriler (ada göre sıralı) ve içlerindeki soru sayısı (arşivliler dahil)."""
    query = (
        select(Category.id, Category.name, func.count(Question.id))
        .outerjoin(Question, Question.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.name)
    )
    with get_session() as session:
        return [CategoryRow(id=i, name=n, question_count=c) for i, n, c in session.execute(query)]


def create_category(name: str) -> int:
    with write_session() as session:
        name = _check_category_name(session, name)
        category = Category(name=name)
        session.add(category)
        session.flush()
        return category.id


def rename_category(category_id: int, name: str) -> None:
    with write_session() as session:
        category = _get_category(session, category_id)
        category.name = _check_category_name(session, name, exclude_id=category_id)


def delete_category(category_id: int) -> None:
    """Boş kategoriyi siler. İçinde soru (arşivli olsa bile) varsa reddeder."""
    with write_session() as session:
        category = _get_category(session, category_id)
        count = session.scalar(
            select(func.count(Question.id)).where(Question.category_id == category_id)
        )
        if count:
            raise QuestionBankError(
                f"'{category.name}' kategorisinde {count} soru var; önce soruları başka "
                "kategoriye taşıyın veya silin."
            )
        session.delete(category)


def _get_category(session: Session, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise QuestionBankError("Kategori bulunamadı (silinmiş olabilir).")
    return category


def _check_category_exists(session: Session, category_id: int | None) -> None:
    if category_id is not None:
        _get_category(session, category_id)


def _check_category_name(session: Session, name: str, exclude_id: int | None = None) -> str:
    """Adı temizler; boşsa, çok uzunsa veya başka kategoride varsa hata verir."""
    name = " ".join(name.split())
    if not name:
        raise QuestionBankError("Kategori adı boş olamaz.")
    if len(name) > MAX_CATEGORY_NAME:
        raise QuestionBankError(f"Kategori adı en fazla {MAX_CATEGORY_NAME} karakter olabilir.")
    for other_id, other_name in session.execute(select(Category.id, Category.name)):
        if other_id != exclude_id and turkish_lower(other_name) == turkish_lower(name):
            raise QuestionBankError(f"'{other_name}' adında bir kategori zaten var.")
    return name


def turkish_lower(text: str) -> str:
    """Türkçe kurallarıyla küçük harf: 'I' → 'ı', 'İ' → 'i' (Python'un lower()'ı bunu bilmez)."""
    return text.replace("I", "ı").replace("İ", "i").lower()
