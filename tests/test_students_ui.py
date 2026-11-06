"""Öğrenciler sekmesi duman testi (ekransız)."""

from pathlib import Path

from tests.qt_utils import qapp, qt_wait_until  # önce gelmeli (offscreen)

from openpyxl import Workbook  # noqa: E402

from instructor_app.ui.student_dialogs import ImportPreviewDialog  # noqa: E402
from instructor_app.ui import students as students_ui  # noqa: E402
from instructor_app.ui.students import StudentsPage  # noqa: E402
from server.services import import_export, students  # noqa: E402


def test_students_page_lists_classes_and_students(seeded_db) -> None:
    qapp()
    page = StudentsPage()
    assert page.class_list.count() == 2
    assert page.current_class().name == "1. Öğretim A"
    assert page.table.rowCount() == 15
    assert page.table.item(0, 0).text() == "260101001"
    assert not page.edit_student_button.isEnabled()

    page.class_list.setCurrentRow(1)
    assert page.table.item(0, 0).text() == "260101016"
    page.table.selectRow(0)
    assert page.edit_student_button.isEnabled() and page.move_button.isEnabled()


def test_import_preview_dialog_and_worker(seeded_db, tmp_path: Path, monkeypatch) -> None:
    qapp()
    # Bilgi kutusu ekransız modda kapanmayı bekleyip testi kilitler; mesajı sadece kaydediyoruz.
    messages: list[str] = []
    monkeypatch.setattr(students_ui.QMessageBox, "information",
                        lambda _parent, _title, text: messages.append(text))
    workbook = Workbook()
    for row in (["Numara", "Adı Soyadı"], ["260202001", "Ali Veli"], ["x", "Hatalı"], ["260101001", "Var"]):
        workbook.active.append(row)
    path = tmp_path / "liste.xlsx"
    workbook.save(path)

    page = StudentsPage()
    preview = import_export.preview_student_import(path)
    dialog = ImportPreviewDialog(preview, students.list_classes(), page.current_class_id())
    assert dialog.import_button.text() == "1 öğrenciyi içe aktar"
    assert dialog.selected_class_id() == page.current_class_id()

    page._start_import(preview.to_add, dialog.selected_class_id())
    qt_wait_until(lambda: page._worker is None and page._progress is None, timeout=10)
    assert page.table.rowCount() == 16
    assert messages and messages[0].startswith("1 öğrenci eklendi")
