"""grading servis testleri: normalize, otomatik puanlama, elle puan, yeniden puanlama."""

import pytest
from sqlalchemy import select

from server.db.models import Answer, ClassicAcceptedAnswer, Submission
from server.db.session import get_session, write_session
from server.services import grading
from server.services.grading import GradingError, normalize_answer
from tests.result_helpers import (
    CLASSIC_POINTS,
    MCQ_POINTS,
    SmallExam,
    answer_id,
    create_small_exam,
    take_exam,
)

STUDENT = "260101001"
STUDENT_2 = "260101002"


@pytest.fixture
def exam(seeded_db) -> SmallExam:
    return create_small_exam()


def total(submission_id: int) -> float | None:
    with get_session() as session:
        return session.get(Submission, submission_id).total_score


def get_answer(submission_id: int, question_id: int) -> Answer:
    with get_session() as session:
        return session.scalar(select(Answer).where(
            Answer.submission_id == submission_id, Answer.question_id == question_id
        ))


# ---------------------------------------------------------------------------
# normalize_answer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("given, expected", [
    ("İSTANBUL", "istanbul"),
    ("ISPARTA", "ısparta"),           # I → ı (Türkçe)
    ("IŞIK", "ışık"),
    ("  Bağlı    Liste  ", "bağlı liste"),
    ("satır\tsonu\nvar", "satır sonu var"),
    ("İstanbul.", "istanbul"),
    ("evet!?", "evet"),
    ("İstanbul", "istanbul"),   # 'İ' iki karakterle yazılmış (I + üst nokta)
    ("", ""),
    (None, ""),
])
def test_normalize_answer(given: str | None, expected: str) -> None:
    assert normalize_answer(given) == expected


def test_normalize_turkish_upper_equals_lower() -> None:
    assert normalize_answer("İSTANBUL") == normalize_answer("istanbul")
    # Python'un kendi lower()'ı bunu yanlış yapar: 'İ'.lower() == 'i̇' (iki karakter)
    assert "İSTANBUL".lower() != "istanbul"


# ---------------------------------------------------------------------------
# grade_submission
# ---------------------------------------------------------------------------

def test_all_correct_gets_full_score(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, option_id=exam.right_option, text="  İSTANBUL. ")
    grading.grade_submission(sid)
    assert total(sid) == MCQ_POINTS + CLASSIC_POINTS
    mcq = get_answer(sid, exam.mcq_id)
    assert mcq.is_correct is True and mcq.points_awarded == MCQ_POINTS
    classic = get_answer(sid, exam.classic_id)
    assert classic.is_correct is True and classic.points_awarded == CLASSIC_POINTS


def test_second_accepted_answer_also_correct(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, text="konstantinopolis")
    grading.grade_submission(sid)
    assert total(sid) == CLASSIC_POINTS


def test_wrong_answers_get_zero(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, option_id=exam.wrong_option, text="Ankara")
    grading.grade_submission(sid)
    assert total(sid) == 0
    assert get_answer(sid, exam.mcq_id).is_correct is False
    assert get_answer(sid, exam.classic_id).is_correct is False


def test_blank_exam_scores_zero(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT)  # hiçbir şey yazmadan gönderdi
    grading.grade_submission(sid)
    assert total(sid) == 0


def test_blank_text_is_not_correct(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, text="   ")
    grading.grade_submission(sid)
    answer = get_answer(sid, exam.classic_id)
    assert answer.is_correct is False and answer.points_awarded == 0


def test_grading_twice_gives_same_result(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, option_id=exam.right_option, text="yanlış")
    grading.grade_submission(sid)
    grading.grade_submission(sid)
    assert total(sid) == MCQ_POINTS


def test_cannot_grade_unsubmitted(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, option_id=exam.right_option, submit=False)
    with pytest.raises(GradingError):
        grading.grade_submission(sid)


def test_grade_unknown_submission(exam: SmallExam) -> None:
    with pytest.raises(GradingError):
        grading.grade_submission(99999)


# ---------------------------------------------------------------------------
# Elle puan
# ---------------------------------------------------------------------------

def test_manual_points_update_total(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, option_id=exam.right_option, text="İstanbul şehri")
    grading.grade_submission(sid)
    assert total(sid) == MCQ_POINTS

    new_total = grading.set_manual_points(answer_id(sid, exam.classic_id), 2.5)
    assert new_total == MCQ_POINTS + 2.5
    assert total(sid) == MCQ_POINTS + 2.5
    answer = get_answer(sid, exam.classic_id)
    assert answer.is_manual is True
    assert answer.is_correct is False  # kısmi puan "doğru" sayılmaz


def test_manual_full_points_counts_as_correct(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, text="İstanbul şehri")
    grading.grade_submission(sid)
    grading.set_manual_points(answer_id(sid, exam.classic_id), CLASSIC_POINTS)
    assert get_answer(sid, exam.classic_id).is_correct is True


@pytest.mark.parametrize("points", [-1, CLASSIC_POINTS + 0.5, float("nan")])
def test_manual_points_out_of_range(exam: SmallExam, points: float) -> None:
    sid = take_exam(exam, STUDENT, text="x")
    grading.grade_submission(sid)
    with pytest.raises(GradingError, match="arasında"):
        grading.set_manual_points(answer_id(sid, exam.classic_id), points)


def test_manual_points_rejected_for_mcq(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, option_id=exam.wrong_option)
    grading.grade_submission(sid)
    with pytest.raises(GradingError, match="Test"):
        grading.set_manual_points(answer_id(sid, exam.mcq_id), MCQ_POINTS)


def test_manual_points_rejected_before_submit(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, text="x", submit=False)
    with pytest.raises(GradingError, match="göndermedi"):
        grading.set_manual_points(answer_id(sid, exam.classic_id), 1)


def test_manual_points_survive_regrade(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, text="İstanbul şehri")
    grading.grade_submission(sid)
    grading.set_manual_points(answer_id(sid, exam.classic_id), 3)
    grading.grade_submission(sid)  # ör. arka plandaki puanlama geç çalıştı
    grading.regrade_exam(exam.exam_id)
    assert get_answer(sid, exam.classic_id).points_awarded == 3
    assert total(sid) == 3


def test_clear_manual_points(exam: SmallExam) -> None:
    sid = take_exam(exam, STUDENT, text="İstanbul şehri")
    grading.grade_submission(sid)
    aid = answer_id(sid, exam.classic_id)
    grading.set_manual_points(aid, 3)
    assert grading.clear_manual_points(aid) == 0
    answer = get_answer(sid, exam.classic_id)
    assert answer.is_manual is False and answer.points_awarded == 0


# ---------------------------------------------------------------------------
# regrade_exam
# ---------------------------------------------------------------------------

def test_regrade_after_answer_key_change(exam: SmallExam) -> None:
    sid1 = take_exam(exam, STUDENT, text="Ankara")
    sid2 = take_exam(exam, STUDENT_2, text="İstanbul")
    unsubmitted = take_exam(exam, "260101003", text="Ankara", submit=False)
    for sid in (sid1, sid2):
        grading.grade_submission(sid)
    assert total(sid1) == 0

    # Eğitmen cevap anahtarına "Ankara"yı da ekledi
    with write_session() as session:
        session.add(ClassicAcceptedAnswer(question_id=exam.classic_id, answer="Ankara"))

    assert grading.regrade_exam(exam.exam_id) == 2  # gönderilmemiş kâğıt atlanır
    assert total(sid1) == CLASSIC_POINTS
    assert total(sid2) == CLASSIC_POINTS
    assert total(unsubmitted) is None


def test_regrade_exam_without_submissions(exam: SmallExam) -> None:
    assert grading.regrade_exam(exam.exam_id) == 0


def test_ungraded_submission_ids(exam: SmallExam) -> None:
    graded = take_exam(exam, STUDENT, option_id=exam.right_option)
    waiting = take_exam(exam, STUDENT_2, option_id=exam.right_option)
    grading.grade_submission(graded)
    assert grading.ungraded_submission_ids() == [waiting]
    grading.grade_submission(waiting)
    assert grading.ungraded_submission_ids() == []
