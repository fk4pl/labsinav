"""Sonuçlar sekmesi duman testi (ekransız): tablo dolar, detayda elle puan verilir."""

import pytest

from tests.qt_utils import qapp  # QT_QPA_PLATFORM=offscreen ayarı için önce bu import edilmeli

from instructor_app.ui.result_detail import StudentResultDialog  # noqa: E402
from instructor_app.ui.results import ResultsPage  # noqa: E402
from server.services import grading, results  # noqa: E402
from tests.result_helpers import create_small_exam, take_exam  # noqa: E402


@pytest.fixture
def graded_exam(seeded_db) -> int:
    exam = create_small_exam()
    grading.grade_submission(take_exam(exam, "260101001", option_id=exam.right_option, text="İstanbul"))
    grading.grade_submission(take_exam(exam, "260101002", option_id=exam.wrong_option, text="Ankara"))
    return exam.exam_id


def test_results_page_shows_exam(graded_exam: int) -> None:
    qapp()
    page = ResultsPage()
    page.reload_exams()
    assert page.current_exam_id() == graded_exam
    assert page.student_model.rowCount() == 15
    assert page.question_model.rowCount() == 2
    assert page.average_card.value_label.text() == "7,5"
    assert page.attendance_card.value_label.text() == "2 / 15"
    assert page.export_button.isEnabled()


def test_results_page_without_exams(seeded_db) -> None:
    qapp()
    page = ResultsPage()
    page.reload_exams()
    assert page.current_exam_id() is None
    assert not page.export_button.isEnabled()


def test_detail_dialog_manual_points(graded_exam: int) -> None:
    qapp()
    row = next(r for r in results.student_results(graded_exam) if r.student_no == "260101002")
    dialog = StudentResultDialog(row.submission_id)
    classic_card = dialog.cards[1]
    assert classic_card.detail.can_edit and not dialog.cards[0].detail.can_edit

    classic_card.points_spin.setValue(2.5)
    classic_card.save_points()

    assert dialog.changed
    assert "2,5" in dialog.info_label.text()
    assert classic_card.reset_button.isVisibleTo(dialog)
    assert results.student_detail(row.submission_id).score == 2.5
