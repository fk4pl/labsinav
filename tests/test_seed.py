from sqlalchemy import func, select

from scripts.seed import seed, summary
from server.db.models import Exam, Question, SchoolClass, User
from server.db.session import get_session, reset_db


def test_seed_counts(seeded_db) -> None:
    with get_session() as session:
        assert summary(session) == {
            "kullanıcı": 31, "sınıf": 2, "kategori": 3, "soru": 20, "sınav": 1,
        }


def test_student_numbers_and_classes(seeded_db) -> None:
    with get_session() as session:
        students = session.scalars(
            select(User).where(User.role == "student").order_by(User.username)
        ).all()
        usernames = [s.username for s in students]
        assert usernames == [str(n) for n in range(260101001, 260101031)]
        class_names = [s.school_class.name for s in students]
        assert class_names[:15] == ["1. Öğretim A"] * 15
        assert class_names[15:] == ["1. Öğretim B"] * 15


def test_question_types_and_answers(seeded_db) -> None:
    with get_session() as session:
        questions = session.scalars(select(Question)).all()
        mcqs = [q for q in questions if q.type == "mcq"]
        classics = [q for q in questions if q.type == "classic"]
        assert len(mcqs) == 12 and len(classics) == 8
        for q in mcqs:
            assert len(q.options) == 4
            assert sum(o.is_correct for o in q.options) == 1
        # Doğru cevap her zaman aynı şıkta olmamalı
        assert len({next(o.order_index for o in q.options if o.is_correct) for q in mcqs}) > 1
        for q in classics:
            assert len(q.accepted_answers) >= 1


def test_draft_exam(seeded_db) -> None:
    with get_session() as session:
        exam = session.scalars(select(Exam)).one()
        assert exam.status == "draft"
        assert exam.duration_minutes == 20
        assert len(exam.exam_questions) == 10
        assert exam.school_class.name == "1. Öğretim A"
        assert exam.created_by is not None


def test_seed_is_repeatable(seeded_db) -> None:
    reset_db()
    with get_session() as session:
        seed(session)
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 31
        assert session.scalar(select(func.count()).select_from(SchoolClass)) == 2
