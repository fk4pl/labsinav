"""results servis testleri: özet istatistikler, öğrenci listesi, detay, soru analizi."""

import pytest

from server.services import grading, results
from server.services.results import ResultsError
from tests.result_helpers import (
    CLASSIC_POINTS,
    MCQ_POINTS,
    SmallExam,
    create_small_exam,
    take_exam,
)

CLASS_SIZE = 15  # seed: 1. Öğretim A


@pytest.fixture
def exam(seeded_db) -> SmallExam:
    """3 gönderen (15, 10, 0 puan), 1 devam eden, 11 girmeyen öğrenci."""
    small = create_small_exam()
    for username, option, text in [
        ("260101001", small.right_option, "İstanbul"),   # 15
        ("260101002", small.right_option, "Ankara"),     # 10
        ("260101003", small.wrong_option, None),         # 0 (klasik boş)
    ]:
        grading.grade_submission(take_exam(small, username, option_id=option, text=text))
    take_exam(small, "260101004", option_id=small.right_option, submit=False)
    return small


def test_list_exams_skips_drafts(exam: SmallExam) -> None:
    exams = results.list_exams()
    assert [e.id for e in exams] == [exam.exam_id]  # seed'deki taslak sınav listede yok
    assert exams[0].class_name == "1. Öğretim A"


def test_exam_summary(exam: SmallExam) -> None:
    summary = results.exam_summary(exam.exam_id)
    assert summary.max_score == MCQ_POINTS + CLASSIC_POINTS
    assert summary.expected_count == CLASS_SIZE
    assert summary.participant_count == 3
    assert summary.graded_count == 3
    assert summary.average == pytest.approx(25 / 3)
    assert summary.median == 10
    assert summary.highest == 15
    assert summary.lowest == 0
    assert summary.std_dev == pytest.approx(6.2361, abs=1e-3)  # pstdev(15, 10, 0)


def test_summary_without_participants(seeded_db) -> None:
    small = create_small_exam()
    summary = results.exam_summary(small.exam_id)
    assert summary.participant_count == 0
    assert summary.average is None and summary.std_dev is None


def test_summary_unknown_exam(seeded_db) -> None:
    with pytest.raises(ResultsError):
        results.exam_summary(12345)


def test_student_results(exam: SmallExam) -> None:
    rows = {r.student_no: r for r in results.student_results(exam.exam_id)}
    assert len(rows) == CLASS_SIZE  # girmeyenler de listede

    first = rows["260101001"]
    assert (first.status, first.score, first.correct, first.wrong, first.blank) == ("submitted", 15, 2, 0, 0)
    assert first.submitted_at is not None and first.auto_submitted is False

    third = rows["260101003"]
    assert (third.score, third.correct, third.wrong, third.blank) == (0, 0, 1, 1)

    assert rows["260101004"].status == "in_progress"
    assert rows["260101004"].score is None
    assert rows["260101005"].status == "absent"
    assert rows["260101005"].submission_id is None


def test_student_detail(exam: SmallExam) -> None:
    sid = next(r.submission_id for r in results.student_results(exam.exam_id) if r.student_no == "260101002")
    detail = results.student_detail(sid)
    assert detail.score == MCQ_POINTS and detail.max_score == MCQ_POINTS + CLASSIC_POINTS

    mcq, classic = detail.answers
    assert mcq.given == "B) 4" and mcq.expected == "B) 4"
    assert mcq.can_edit is False  # test sorusu elle değiştirilemez
    assert classic.given == "Ankara"
    assert classic.expected == "İstanbul / Konstantinopolis"
    assert classic.points == 0 and classic.can_edit is True


def test_student_detail_unknown(seeded_db) -> None:
    with pytest.raises(ResultsError):
        results.student_detail(999)


def test_question_stats(exam: SmallExam) -> None:
    mcq, classic = results.question_stats(exam.exam_id)

    assert (mcq.correct, mcq.wrong, mcq.blank) == (2, 1, 0)
    assert mcq.correct_rate == pytest.approx(2 / 3)
    assert [(o.letter, o.count, o.is_correct) for o in mcq.options] == [
        ("A", 1, False), ("B", 2, True), ("C", 0, False),
    ]

    assert (classic.correct, classic.wrong, classic.blank) == (1, 1, 1)
    assert classic.correct_rate == pytest.approx(1 / 3)
    assert classic.options == []


def test_question_stats_include_partial_points(exam: SmallExam) -> None:
    sid = next(r.submission_id for r in results.student_results(exam.exam_id) if r.student_no == "260101002")
    detail = results.student_detail(sid)
    grading.set_manual_points(detail.answers[1].answer_id, 2.5)

    classic = results.question_stats(exam.exam_id)[1]
    assert classic.correct == 1  # kısmi puan doğru sayılmaz…
    assert classic.average_rate == pytest.approx((5 + 2.5) / (5 * 3))  # …ama ortalamaya girer
