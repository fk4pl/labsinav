"""Soru bankası servisi testleri (server/services/question_bank.py)."""

import pytest
from sqlalchemy import select

from server.db.models import Exam, ExamQuestion, Question, QuestionOption
from server.db.session import get_session, write_session
from server.services import question_bank as qb
from server.services.question_bank import OptionDraft, QuestionBankError, QuestionDraft


def mcq_draft(**changes) -> QuestionDraft:
    draft = QuestionDraft(
        type="mcq",
        text="int dizinin ilk elemanının indisi kaçtır?",
        category_id=None,
        default_points=10,
        options=[OptionDraft("0", True), OptionDraft("1"), OptionDraft("-1")],
    )
    for key, value in changes.items():
        setattr(draft, key, value)
    return draft


def classic_draft(**changes) -> QuestionDraft:
    draft = QuestionDraft(
        type="classic", text="Dizinin boyutunu veren operatör?", category_id=None,
        default_points=5, accepted_answers=["sizeof"],
    )
    for key, value in changes.items():
        setattr(draft, key, value)
    return draft


def add_to_exam(question_id: int, status: str) -> None:
    """Soruyu verilen durumda yeni bir sınava ekler."""
    with write_session() as session:
        exam = Exam(title="Deneme", duration_minutes=20, status=status)
        exam.exam_questions = [ExamQuestion(question_id=question_id, points=10, order_index=0)]
        session.add(exam)


# ---------------------------------------------------------------------------
# Doğrulama
# ---------------------------------------------------------------------------

def test_valid_drafts_have_no_errors() -> None:
    assert qb.validate_draft(mcq_draft()) == []
    assert qb.validate_draft(classic_draft()) == []


@pytest.mark.parametrize(
    ("draft", "expected"),
    [
        (mcq_draft(text="   \n "), "Soru metni boş olamaz."),
        (mcq_draft(default_points=0), "Puan 0,5 ile 100 arasında olmalı."),
        (mcq_draft(options=[OptionDraft("tek", True)]), "2 ile 6 arasında"),
        (mcq_draft(options=[OptionDraft(str(i), i == 0) for i in range(7)]), "2 ile 6 arasında"),
        (mcq_draft(options=[OptionDraft("a", True), OptionDraft("  ")]), "Boş şık"),
        (mcq_draft(options=[OptionDraft("a", True), OptionDraft("a")]), "Aynı metne"),
        (mcq_draft(options=[OptionDraft("a"), OptionDraft("b")]), "Tam olarak bir doğru"),
        (mcq_draft(options=[OptionDraft("a", True), OptionDraft("b", True)]), "Tam olarak bir doğru"),
        (classic_draft(accepted_answers=[]), "En az bir kabul edilen"),
        (classic_draft(accepted_answers=["  ", ""]), "En az bir kabul edilen"),
        (mcq_draft(type="code"), "Final'de eklenecek"),
    ],
)
def test_validation_errors(draft: QuestionDraft, expected: str) -> None:
    errors = qb.validate_draft(draft)
    assert any(expected in e for e in errors), errors


def test_create_rejects_invalid_draft(empty_db) -> None:
    with pytest.raises(QuestionBankError, match="Boş şık"):
        qb.create_question(mcq_draft(options=[OptionDraft("a", True), OptionDraft("")]))
    assert qb.list_questions() == []


def test_create_rejects_unknown_category(empty_db) -> None:
    with pytest.raises(QuestionBankError, match="Kategori bulunamadı"):
        qb.create_question(mcq_draft(category_id=999))


# ---------------------------------------------------------------------------
# Ekleme / okuma / filtreleme
# ---------------------------------------------------------------------------

def test_create_and_get_mcq(empty_db) -> None:
    category_id = qb.create_category("Diziler")
    question_id = qb.create_question(mcq_draft(category_id=category_id))

    detail = qb.get_question(question_id)
    assert detail.draft.type == "mcq"
    assert detail.draft.category_id == category_id
    assert [o.text for o in detail.draft.options] == ["0", "1", "-1"]
    assert [o.is_correct for o in detail.draft.options] == [True, False, False]
    assert not detail.is_archived and not detail.used_in_started_exam


def test_create_classic_cleans_answers(empty_db) -> None:
    question_id = qb.create_question(
        classic_draft(accepted_answers=["  sizeof ", "sizeof", "", "sizeof()"])
    )
    assert qb.get_question(question_id).draft.accepted_answers == ["sizeof", "sizeof()"]


def test_list_filters(empty_db) -> None:
    arrays = qb.create_category("Diziler")
    loops = qb.create_category("Döngüler")
    mcq_id = qb.create_question(mcq_draft(category_id=arrays))
    classic_id = qb.create_question(classic_draft(category_id=loops))

    assert {r.id for r in qb.list_questions()} == {mcq_id, classic_id}
    assert [r.id for r in qb.list_questions(category_id=arrays)] == [mcq_id]
    assert [r.id for r in qb.list_questions(question_type="classic")] == [classic_id]
    assert [r.id for r in qb.list_questions(search="operatör")] == [classic_id]
    assert qb.list_questions()[0].category_name in {"Diziler", "Döngüler"}


def test_make_preview_shortens_to_single_line() -> None:
    assert qb.make_preview("a\n   b") == "a b"
    long_text = "x" * 100
    assert qb.make_preview(long_text) == "x" * 80 + "…"


def test_seeded_bank_lists_all_questions(seeded_db) -> None:
    assert len(qb.list_questions()) == 20


# ---------------------------------------------------------------------------
# Düzenleme
# ---------------------------------------------------------------------------

def test_update_changes_options(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    new_options = [OptionDraft("a"), OptionDraft("b", True)]
    qb.update_question(question_id, mcq_draft(text="Yeni metin", options=new_options))

    detail = qb.get_question(question_id)
    assert detail.draft.text == "Yeni metin"
    assert [(o.text, o.is_correct) for o in detail.draft.options] == [("a", False), ("b", True)]
    with get_session() as session:  # eski şıklar veri tabanında kalmamalı
        assert len(session.scalars(select(QuestionOption)).all()) == 2


def test_update_mcq_to_classic_removes_options(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    qb.update_question(question_id, classic_draft())

    detail = qb.get_question(question_id)
    assert detail.draft.type == "classic"
    assert detail.draft.options == []
    assert detail.draft.accepted_answers == ["sizeof"]


def test_update_refreshes_updated_at(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    before = qb.list_questions()[0].updated_at
    qb.update_question(question_id, mcq_draft(options=[OptionDraft("x", True), OptionDraft("y")]))
    assert qb.list_questions()[0].updated_at > before


def test_update_allowed_when_only_in_draft_exam(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    add_to_exam(question_id, "draft")
    qb.update_question(question_id, mcq_draft(text="Değişti"))
    assert qb.get_question(question_id).draft.text == "Değişti"


@pytest.mark.parametrize("status", ["running", "finished"])
def test_update_rejected_when_used_in_started_exam(empty_db, status: str) -> None:
    question_id = qb.create_question(mcq_draft())
    add_to_exam(question_id, status)

    assert qb.get_question(question_id).used_in_started_exam
    with pytest.raises(QuestionBankError, match="değiştirilemez"):
        qb.update_question(question_id, mcq_draft(text="Değişti"))


def test_update_rejects_invalid_draft(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    with pytest.raises(QuestionBankError, match="Soru metni boş"):
        qb.update_question(question_id, mcq_draft(text=""))


# ---------------------------------------------------------------------------
# Silme / arşivleme / çoğaltma / önizleme
# ---------------------------------------------------------------------------

def test_delete_unused_question(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    assert qb.delete_question(question_id) == "deleted"
    with get_session() as session:
        assert session.get(Question, question_id) is None
        assert session.scalars(select(QuestionOption)).all() == []


def test_delete_used_question_archives_it(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    add_to_exam(question_id, "draft")

    assert qb.delete_question(question_id) == "archived"
    assert qb.list_questions() == []
    archived = qb.list_questions(include_archived=True)
    assert [r.id for r in archived] == [question_id] and archived[0].is_archived

    qb.restore_question(question_id)
    assert [r.id for r in qb.list_questions()] == [question_id]


def test_duplicate_copies_options(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    add_to_exam(question_id, "finished")
    copy_id = qb.duplicate_question(question_id)

    assert copy_id != question_id
    original, copy = qb.get_question(question_id), qb.get_question(copy_id)
    assert copy.draft == original.draft
    assert not copy.used_in_started_exam  # kopya serbestçe düzenlenebilir


def test_preview_has_no_answer_key(empty_db) -> None:
    question_id = qb.create_question(mcq_draft())
    preview = qb.preview_question(question_id)
    assert [o.text for o in preview.options] == ["0", "1", "-1"]
    dumped = preview.model_dump_json()
    assert "is_correct" not in dumped

    classic_preview = qb.preview_question(qb.create_question(classic_draft()))
    assert "sizeof" not in classic_preview.model_dump_json()


def test_missing_question_raises(empty_db) -> None:
    with pytest.raises(QuestionBankError, match="bulunamadı"):
        qb.get_question(12345)


# ---------------------------------------------------------------------------
# Kategoriler
# ---------------------------------------------------------------------------

def test_category_create_and_duplicate_name(empty_db) -> None:
    qb.create_category("  İşaretçiler  ")
    assert [c.name for c in qb.list_categories()] == ["İşaretçiler"]
    with pytest.raises(QuestionBankError, match="zaten var"):
        qb.create_category("işaretçiler")  # Türkçe küçük harf: İ → i
    with pytest.raises(QuestionBankError, match="boş olamaz"):
        qb.create_category("   ")


def test_category_rename(empty_db) -> None:
    category_id = qb.create_category("Dizi")
    other_id = qb.create_category("Döngüler")
    qb.rename_category(category_id, "Diziler")
    qb.rename_category(category_id, "DİZİLER")  # kendi adının farklı yazımı serbest
    with pytest.raises(QuestionBankError, match="zaten var"):
        qb.rename_category(other_id, "diziler")


def test_category_delete_rules(empty_db) -> None:
    used_id = qb.create_category("Dolu")
    empty_id = qb.create_category("Boş")
    qb.create_question(mcq_draft(category_id=used_id))

    counts = {c.name: c.question_count for c in qb.list_categories()}
    assert counts == {"Dolu": 1, "Boş": 0}

    with pytest.raises(QuestionBankError, match="1 soru var"):
        qb.delete_category(used_id)
    qb.delete_category(empty_id)
    assert [c.name for c in qb.list_categories()] == ["Dolu"]


def test_turkish_lower() -> None:
    assert qb.turkish_lower("IŞIK İĞNE") == "ışık iğne"


# ---------------------------------------------------------------------------
# Puan sınırları (config.MIN_QUESTION_POINTS … config.MAX_QUESTION_POINTS)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("points", [0.5, 1, 10, 99.5, 100])
def test_points_inside_limits_are_valid(points: float) -> None:
    assert qb.points_error(points) is None
    assert qb.validate_draft(mcq_draft(default_points=points)) == []


@pytest.mark.parametrize("points", [0, 0.4, -5, 100.5, 1000, float("nan"), float("inf")])
def test_points_outside_limits_are_rejected(points: float) -> None:
    assert qb.points_error(points) == "Puan 0,5 ile 100 arasında olmalı."
    assert "Puan 0,5 ile 100 arasında olmalı." in qb.validate_draft(mcq_draft(default_points=points))


def test_create_question_with_too_many_points_fails(empty_db) -> None:
    with pytest.raises(qb.QuestionBankError, match="0,5 ile 100"):
        qb.create_question(classic_draft(default_points=150))


@pytest.mark.parametrize("given, expected", [(150, 100), (0.1, 0.5), (25, 25), (float("nan"), 0.5)])
def test_clamp_points(given: float, expected: float) -> None:
    assert qb.clamp_points(given) == expected
