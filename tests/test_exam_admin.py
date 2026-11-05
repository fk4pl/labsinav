"""exam_admin servis testleri (sınav CRUD, rastgele soru, canlı panel verisi)."""

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from scripts.seed import CLASS_A, CLASS_B, DRAFT_EXAM_TITLE
from server.db.models import Exam, Question, SchoolClass, User
from server.db.session import get_session, write_session
from server.services import exam_admin, exam_session, question_bank
from server.services.event_log import Event, log_event
from server.services.exam_admin import ExamAdminError, ExamDraft, ExamQuestionDraft
from shared.protocol import SaveAnswerRequest

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
IP = "192.168.1.20"


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def class_id(name: str) -> int:
    with get_session() as session:
        return session.scalar(select(SchoolClass.id).where(SchoolClass.name == name))


def user_id(username: str) -> int:
    with get_session() as session:
        return session.scalar(select(User.id).where(User.username == username))


def seeded_exam_id() -> int:
    with get_session() as session:
        return session.scalar(select(Exam.id).where(Exam.title == DRAFT_EXAM_TITLE))


def question_ids(count: int, qtype: str | None = None) -> list[int]:
    rows = question_bank.list_questions(question_type=qtype)
    return sorted(r.id for r in rows)[:count]


def make_draft(ids: list[int], title: str = "Quiz 1", points: float = 5) -> ExamDraft:
    return ExamDraft(
        title=title, class_id=class_id(CLASS_A), duration_minutes=30,
        questions=[ExamQuestionDraft(qid, points) for qid in ids],
    )


def set_status(exam_id: int, status: str) -> None:
    with write_session() as session:
        session.get(Exam, exam_id).status = status


# ---------------------------------------------------------------------------
# Sınıflar ve liste
# ---------------------------------------------------------------------------

def test_list_classes_counts_students(seeded_db) -> None:
    classes = {c.name: c.student_count for c in exam_admin.list_classes()}
    assert classes == {CLASS_A: 15, CLASS_B: 15}


def test_list_exams_shows_seeded_exam(seeded_db) -> None:
    rows = exam_admin.list_exams()
    assert len(rows) == 1
    row = rows[0]
    assert row.title == DRAFT_EXAM_TITLE
    assert row.class_name == CLASS_A
    assert row.question_count == 10
    assert row.total_points == 100
    assert row.status == "draft"


# ---------------------------------------------------------------------------
# Oluşturma / düzenleme
# ---------------------------------------------------------------------------

def test_create_and_get_exam_keeps_order_and_points(seeded_db) -> None:
    ids = question_ids(3)
    draft = make_draft(list(reversed(ids)))
    draft.questions[0].points = 2.5
    exam_id = exam_admin.create_exam(draft, created_by=None)

    detail = exam_admin.get_exam(exam_id)
    assert [q.question_id for q in detail.questions] == list(reversed(ids))
    assert [q.points for q in detail.questions] == [2.5, 5, 5]
    assert detail.row.total_points == 12.5
    assert detail.row.status == "draft"


def test_validate_exam_draft_errors() -> None:
    draft = ExamDraft(
        title="  ", class_id=None, duration_minutes=0,
        questions=[ExamQuestionDraft(1, 0), ExamQuestionDraft(1, 5)],
    )
    errors = exam_admin.validate_exam_draft(draft)
    assert len(errors) == 5


def test_create_exam_rejects_invalid(seeded_db) -> None:
    with pytest.raises(ExamAdminError, match="Sınav adı"):
        exam_admin.create_exam(make_draft([], title=""), created_by=None)


def test_create_exam_rejects_missing_question(seeded_db) -> None:
    with pytest.raises(ExamAdminError, match="bulunamadı"):
        exam_admin.create_exam(make_draft([99999]), created_by=None)


def test_create_exam_rejects_archived_question(seeded_db) -> None:
    qid = question_ids(1)[0]
    with write_session() as session:
        session.get(Question, qid).is_archived = True
    with pytest.raises(ExamAdminError, match="Arşiv"):
        exam_admin.create_exam(make_draft([qid]), created_by=None)


def test_update_exam_replaces_questions(seeded_db) -> None:
    exam_id = seeded_exam_id()
    old_ids = [q.question_id for q in exam_admin.get_exam(exam_id).questions]
    new_ids = [old_ids[2], old_ids[0]]  # bir kısmı aynı, sırası farklı
    exam_admin.update_exam(exam_id, make_draft(new_ids, title="Yeni ad", points=7))

    detail = exam_admin.get_exam(exam_id)
    assert detail.row.title == "Yeni ad"
    assert [q.question_id for q in detail.questions] == new_ids
    assert detail.row.total_points == 14


@pytest.mark.parametrize("status", ["running", "finished"])
def test_update_and_delete_only_draft(seeded_db, status: str) -> None:
    exam_id = seeded_exam_id()
    set_status(exam_id, status)
    with pytest.raises(ExamAdminError, match="taslak"):
        exam_admin.update_exam(exam_id, make_draft(question_ids(1)))
    with pytest.raises(ExamAdminError, match="taslak"):
        exam_admin.delete_exam(exam_id)


def test_delete_draft_exam(seeded_db) -> None:
    exam_id = seeded_exam_id()
    exam_admin.delete_exam(exam_id)
    assert exam_admin.list_exams() == []
    with pytest.raises(ExamAdminError):
        exam_admin.get_exam(exam_id)


def test_duplicate_finished_exam_creates_draft_copy(seeded_db) -> None:
    exam_id = seeded_exam_id()
    set_status(exam_id, "finished")
    copy_id = exam_admin.duplicate_exam(exam_id)

    original = exam_admin.get_exam(exam_id)
    copy = exam_admin.get_exam(copy_id)
    assert copy.row.status == "draft"
    assert copy.row.title == f"{DRAFT_EXAM_TITLE} (kopya)"
    assert copy.questions == original.questions


# ---------------------------------------------------------------------------
# Rastgele soru
# ---------------------------------------------------------------------------

def test_pick_random_questions_respects_category_and_exclude(seeded_db) -> None:
    category = question_bank.list_categories()[0]
    in_category = [q.id for q in question_bank.list_questions(category_id=category.id)]
    excluded = {in_category[0]}

    picked = exam_admin.pick_random_questions(category.id, 2, excluded, rng=random.Random(1))
    assert len(picked) == 2
    assert all(q.category_id == category.id for q in picked)
    assert not excluded & {q.id for q in picked}


def test_pick_random_questions_returns_all_when_not_enough(seeded_db) -> None:
    all_ids = {q.id for q in question_bank.list_questions()}
    picked = exam_admin.pick_random_questions(None, 1000, exclude_ids=set())
    assert {q.id for q in picked} == all_ids


# ---------------------------------------------------------------------------
# Canlı panel
# ---------------------------------------------------------------------------

def test_live_snapshot(seeded_db) -> None:
    exam_id = seeded_exam_id()
    exam_session.start_exam(exam_id, T0)
    s1, s2 = user_id("260101001"), user_id("260101002")
    first_classic = next(q for q in exam_admin.get_exam(exam_id).questions if q.type == "classic")

    exam_session.open_submission(exam_id, s1, IP, T0 + timedelta(minutes=1))
    request = SaveAnswerRequest(exam_id=exam_id, question_id=first_classic.question_id, text_answer="x")
    exam_session.save_answer(s1, request, IP, T0 + timedelta(minutes=2))
    exam_session.open_submission(exam_id, s2, IP, T0 + timedelta(minutes=1))
    exam_session.submit(s2, exam_id, IP, T0 + timedelta(minutes=3))
    for _ in range(2):
        log_event(Event.FOCUS_LOST, username="260101001", exam_id=exam_id, at=T0)

    snapshot = exam_admin.get_live_snapshot(exam_id)
    assert snapshot.status == "running"
    assert snapshot.question_count == 10
    assert len(snapshot.students) == 15  # sınıfın tüm öğrencileri
    rows = {r.username: r for r in snapshot.students}
    assert rows["260101001"].submission_status == "in_progress"
    assert rows["260101001"].answered_count == 1
    assert rows["260101001"].focus_lost_count == 2
    assert rows["260101001"].last_activity == T0 + timedelta(minutes=2)
    assert rows["260101001"].ip == IP
    assert rows["260101002"].submission_status == "submitted"
    assert rows["260101002"].last_activity == T0 + timedelta(minutes=3)
    assert rows["260101003"].submission_status is None
    assert rows["260101003"].focus_lost_count == 0

    assert [e.id for e in exam_admin.list_running_exams()] == [exam_id]
