"""Öğrenciler sekmesi: sınıflar, öğrenciler, Excel/CSV'den içe aktarma. (Sahibi: D — P6)

Sol: sınıf listesi (ekle / yeniden adlandır / sil). Sağ: seçili sınıfın öğrencileri.
Bütün kurallar (öğrencisi olan sınıf silinemez, no benzersiz vb.) servislerdedir:
server/services/students.py ve server/services/import_export.py. Bu dosya sadece onları çağırır
ve gelen Türkçe hata mesajını gösterir.
"""

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.student_dialogs import ImportPreviewDialog, ImportWorker, StudentDialog
from instructor_app.ui.widgets import make_button
from server.services import import_export, students
from server.services.exam_admin import ClassRow
from server.services.import_export import ImportFileError, ImportRow
from server.services.students import StudentAdminError, StudentRow

FILE_FILTER = "Öğrenci listesi (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)"


class StudentsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: ImportWorker | None = None
        self._progress: QProgressDialog | None = None
        self._import_class_id: int | None = None
        self._build_ui()
        self.reload()

    # ------------------------------------------------------------------
    # Arayüz
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.class_list = QListWidget()
        self.class_list.currentItemChanged.connect(self._on_class_changed)
        self.class_list.itemDoubleClicked.connect(self._rename_class)
        self.add_class_button = make_button("Ekle")
        self.add_class_button.clicked.connect(self._add_class)
        self.rename_class_button = make_button("Yeniden adlandır", "secondary")
        self.rename_class_button.clicked.connect(self._rename_class)
        self.delete_class_button = make_button("Sil", "danger")
        self.delete_class_button.clicked.connect(self._delete_class)

        class_title = QLabel("Sınıflar")
        class_title.setObjectName("title")
        class_buttons = QHBoxLayout()
        for button in (self.add_class_button, self.rename_class_button, self.delete_class_button):
            class_buttons.addWidget(button)
        left = QVBoxLayout()
        left.addWidget(class_title)
        left.addWidget(self.class_list, stretch=1)
        left.addLayout(class_buttons)

        self.students_title = QLabel()
        self.students_title.setObjectName("title")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Öğrenci No", "Ad Soyad"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(self._edit_student)

        self.add_student_button = make_button("Öğrenci ekle")
        self.add_student_button.clicked.connect(self._add_student)
        self.edit_student_button = make_button("Düzenle", "secondary")
        self.edit_student_button.clicked.connect(self._edit_student)
        self.reset_password_button = make_button("Şifre sıfırla", "secondary")
        self.reset_password_button.clicked.connect(self._reset_password)
        self.move_button = make_button("Sınıfa taşı", "secondary")
        self.move_button.clicked.connect(self._move_students)
        self.import_button = make_button("Excel/CSV'den içe aktar")
        self.import_button.clicked.connect(self._import)
        self.template_button = make_button("Örnek şablonu indir", "secondary")
        self.template_button.clicked.connect(self._save_template)

        student_buttons = QHBoxLayout()
        for button in (self.add_student_button, self.edit_student_button,
                       self.reset_password_button, self.move_button):
            student_buttons.addWidget(button)
        student_buttons.addStretch()
        student_buttons.addWidget(self.template_button)
        student_buttons.addWidget(self.import_button)

        right = QVBoxLayout()
        right.addWidget(self.students_title)
        right.addWidget(self.table, stretch=1)
        right.addLayout(student_buttons)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(280)
        layout.addWidget(left_widget)
        layout.addLayout(right, stretch=1)

    def showEvent(self, event: QShowEvent) -> None:
        """Sekmeye her gelindiğinde liste yenilenir (sınıflar başka sekmede de değişebilir)."""
        super().showEvent(event)
        self.reload(self.current_class_id())

    # ------------------------------------------------------------------
    # Listeleri doldurma
    # ------------------------------------------------------------------

    def reload(self, select_class_id: int | None = None) -> None:
        self.class_list.blockSignals(True)
        self.class_list.clear()
        for row in students.list_classes():
            item = QListWidgetItem(f"{row.name}   ({row.student_count} öğrenci)")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.class_list.addItem(item)
            if row.id == select_class_id:
                self.class_list.setCurrentItem(item)
        if self.class_list.currentItem() is None and self.class_list.count():
            self.class_list.setCurrentRow(0)
        self.class_list.blockSignals(False)
        self._load_students()

    def current_class(self) -> ClassRow | None:
        item = self.class_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def current_class_id(self) -> int | None:
        current = self.current_class()
        return current.id if current else None

    def _on_class_changed(self, *_args: object) -> None:
        self._load_students()

    def _load_students(self) -> None:
        current = self.current_class()
        rows = students.list_students(current.id) if current else []
        self.students_title.setText(f"{current.name} — {len(rows)} öğrenci" if current else "Sınıf seçin")
        self.table.setRowCount(len(rows))
        for r, student in enumerate(rows):
            no_item = QTableWidgetItem(student.student_no)
            no_item.setData(Qt.ItemDataRole.UserRole, student)
            self.table.setItem(r, 0, no_item)
            self.table.setItem(r, 1, QTableWidgetItem(student.full_name))
        self._update_buttons()

    def selected_students(self) -> list[StudentRow]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]

    def _update_buttons(self) -> None:
        has_class = self.current_class() is not None
        selected = len(self.selected_students())
        self.rename_class_button.setEnabled(has_class)
        self.delete_class_button.setEnabled(has_class)
        self.add_student_button.setEnabled(has_class)
        self.edit_student_button.setEnabled(selected == 1)
        self.reset_password_button.setEnabled(selected == 1)
        self.move_button.setEnabled(selected > 0 and self.class_list.count() > 1)

    # ------------------------------------------------------------------
    # Sınıf işlemleri
    # ------------------------------------------------------------------

    def _add_class(self) -> None:
        name, ok = QInputDialog.getText(self, "Sınıf ekle", "Sınıf adı (ör. 1. Öğretim A):")
        if ok:
            new_id = self._run(students.create_class, name)
            if new_id is not None:
                self.reload(new_id)

    def _rename_class(self, *_args: object) -> None:
        current = self.current_class()
        if current is None:
            return
        name, ok = QInputDialog.getText(self, "Yeniden adlandır", "Yeni ad:", text=current.name)
        if ok and self._run(students.rename_class, current.id, name) is not None:
            self.reload(current.id)

    def _delete_class(self) -> None:
        current = self.current_class()
        if current is None:
            return
        answer = QMessageBox.question(self, "Sınıf sil", f"'{current.name}' sınıfı silinsin mi?")
        if answer == QMessageBox.StandardButton.Yes and self._run(students.delete_class, current.id) is not None:
            self.reload()

    # ------------------------------------------------------------------
    # Öğrenci işlemleri
    # ------------------------------------------------------------------

    def _add_student(self) -> None:
        current = self.current_class()
        if current is None:
            return
        dialog = StudentDialog(f"Öğrenci ekle — {current.name}", self._create_in_current_class, parent=self)
        if dialog.exec():
            QMessageBox.information(self, "Öğrenci eklendi", "Öğrencinin başlangıç şifresi öğrenci numarasıdır.")
            self.reload(current.id)
        dialog.deleteLater()

    def _create_in_current_class(self, student_no: str, full_name: str) -> None:
        current = self.current_class()
        assert current is not None
        students.create_student(student_no, full_name, current.id)

    def _edit_student(self, *_args: object) -> None:
        selected = self.selected_students()
        if len(selected) != 1:
            return
        student = selected[0]
        save = partial(students.update_student, student.id)  # save(no, ad) → update_student(id, no, ad)
        dialog = StudentDialog("Öğrenciyi düzenle", save, student.student_no, student.full_name, parent=self)
        if dialog.exec():
            self.reload(self.current_class_id())
        dialog.deleteLater()

    def _reset_password(self) -> None:
        selected = self.selected_students()
        if len(selected) != 1:
            return
        student = selected[0]
        answer = QMessageBox.question(
            self, "Şifre sıfırla",
            f"{student.full_name} ({student.student_no}) öğrencisinin şifresi öğrenci numarasına döndürülsün mü?",
        )
        if answer == QMessageBox.StandardButton.Yes and self._run(students.reset_password, student.id) is not None:
            QMessageBox.information(self, "Şifre sıfırlandı", f"Yeni şifre: {student.student_no}")

    def _move_students(self) -> None:
        selected = self.selected_students()
        current_id = self.current_class_id()
        targets = [row for row in students.list_classes() if row.id != current_id]
        if not selected or not targets:
            return
        name, ok = QInputDialog.getItem(self, "Sınıfa taşı", f"{len(selected)} öğrenci hangi sınıfa taşınsın?",
                                        [row.name for row in targets], editable=False)
        if not ok:
            return
        target = next(row for row in targets if row.name == name)
        if self._run(students.move_students, [s.id for s in selected], target.id) is not None:
            self.reload(current_id)

    # ------------------------------------------------------------------
    # İçe aktarma ve şablon
    # ------------------------------------------------------------------

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Öğrenci listesi seç", "", FILE_FILTER)
        if not path:
            return
        try:
            preview = import_export.preview_student_import(path)
        except ImportFileError as error:
            QMessageBox.warning(self, "Dosya okunamadı", error.message)
            return
        dialog = ImportPreviewDialog(preview, students.list_classes(), self.current_class_id(), self)
        accepted = dialog.exec()
        class_id = dialog.selected_class_id()
        dialog.deleteLater()
        if accepted and class_id is not None:
            self._start_import(preview.to_add, class_id)

    def _start_import(self, rows: list[ImportRow], class_id: int) -> None:
        self._import_class_id = class_id
        self._progress = QProgressDialog("Öğrenciler ekleniyor, lütfen bekleyin…", "", 0, 0, self)
        self._progress.setWindowTitle("İçe aktarma")
        self._progress.setCancelButton(None)  # yarıda kesilemez (tek seferde yazılır)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.show()
        self._worker = ImportWorker(rows, class_id, self)
        self._worker.succeeded.connect(self._on_import_succeeded)
        self._worker.failed.connect(self._on_import_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_import_succeeded(self, added: int) -> None:
        self._close_progress()
        self.reload(self._import_class_id)
        QMessageBox.information(self, "İçe aktarma tamamlandı",
                                f"{added} öğrenci eklendi. Başlangıç şifreleri öğrenci numaralarıdır.")

    def _on_import_failed(self, message: str) -> None:
        self._close_progress()
        QMessageBox.warning(self, "İçe aktarma başarısız", message)

    def _on_worker_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def _save_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Şablonu kaydet", "ogrenci_listesi_sablonu.xlsx",
                                              "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            import_export.write_student_template(path)
        except OSError:
            QMessageBox.warning(self, "Kaydedilemedi",
                                "Şablon kaydedilemedi. Dosya başka bir programda açık olabilir.")
            return
        QMessageBox.information(self, "Şablon kaydedildi", f"Şablon kaydedildi:\n{path}")

    # ------------------------------------------------------------------

    def _run(self, action, *args) -> object | None:
        """Servis fonksiyonunu çağırır; kural hatası olursa Türkçe mesaj gösterir ve None döner."""
        try:
            result = action(*args)
        except StudentAdminError as error:
            QMessageBox.warning(self, "İşlem yapılamadı", error.message)
            return None
        return result if result is not None else True
