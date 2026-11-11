"""Öğrenciler sekmesinin diyalogları. (Sahibi: D)

StudentDialog        tek öğrenci ekleme / düzenleme
ImportPreviewDialog  Excel/CSV içe aktarma önizlemesi (eklenecek / zaten var / hatalı)
ImportWorker         onaydan sonra öğrencileri arka planda ekler (bcrypt yavaş; arayüz donmasın)
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.widgets import make_button, make_error_box, show_errors
from server.services import import_export, students
from server.services.exam_admin import ClassRow
from server.services.import_export import ImportPreview, ImportRow
from server.services.students import StudentAdminError

logger = logging.getLogger(__name__)


class StudentDialog(QDialog):
    """Öğrenci no ve ad soyad sorar. Kaydet'e basınca save_action(no, ad) çağrılır;
    StudentAdminError gelirse diyalog açık kalır ve hata kırmızı kutuda gösterilir."""

    def __init__(self, title: str, save_action: Callable[[str, str], None],
                 student_no: str = "", full_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self._save_action = save_action

        self.no_input = QLineEdit(student_no)
        self.no_input.setMaxLength(students.MAX_STUDENT_NO)
        self.no_input.setPlaceholderText("ör. 260101001")
        self.name_input = QLineEdit(full_name)
        self.name_input.setMaxLength(students.MAX_FULL_NAME)
        self.error_box = make_error_box()

        form = QFormLayout()
        form.addRow("Öğrenci No:", self.no_input)
        form.addRow("Ad Soyad:", self.name_input)

        save_button = make_button("Kaydet")
        save_button.clicked.connect(self._save)
        cancel_button = make_button("Vazgeç", "secondary")
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error_box)
        layout.addLayout(buttons)

    def _save(self) -> None:
        try:
            self._save_action(self.no_input.text(), self.name_input.text())
        except StudentAdminError as error:
            show_errors(self.error_box, [error.message])
            return
        self.accept()


class ImportPreviewDialog(QDialog):
    """İçe aktarma önizlemesi. accept() olursa selected_class_id() hedef sınıfı verir."""

    def __init__(self, preview: ImportPreview, classes: list[ClassRow], class_id: int | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("İçe aktarma önizlemesi")
        self.resize(720, 520)
        self.preview = preview

        self.class_combo = QComboBox()
        for row in classes:
            self.class_combo.addItem(row.name, row.id)
            if row.id == class_id:
                self.class_combo.setCurrentIndex(self.class_combo.count() - 1)

        summary = QLabel(
            f"Eklenecek: {len(preview.to_add)}  ·  Zaten var: {len(preview.existing)}  ·  "
            f"Hatalı satır: {len(preview.errors)}"
        )
        summary.setObjectName("subtitle")
        note = QLabel("Başlangıç şifresi öğrenci numarasıdır. Zaten var olan öğrenciler değiştirilmez "
                      "ve başka sınıfa taşınmaz. Boş satırlar atlanır.")
        note.setWordWrap(True)

        tabs = QTabWidget()
        tabs.addTab(_table(["Satır", "Öğrenci No", "Ad Soyad"],
                           [[r.row_number, r.student_no, r.full_name] for r in preview.to_add]),
                    f"Eklenecek ({len(preview.to_add)})")
        tabs.addTab(_table(["Satır", "Öğrenci No", "Ad Soyad", "Bulunduğu sınıf"],
                           [[r.row_number, r.student_no, r.full_name, r.place] for r in preview.existing]),
                    f"Zaten var ({len(preview.existing)})")
        tabs.addTab(_table(["Satır", "Neden"], [[e.row_number, e.reason] for e in preview.errors]),
                    f"Hatalı ({len(preview.errors)})")
        if preview.errors and not preview.to_add:
            tabs.setCurrentIndex(2)

        self.import_button = make_button(f"{len(preview.to_add)} öğrenciyi içe aktar")
        self.import_button.setEnabled(bool(preview.to_add) and self.class_combo.count() > 0)
        self.import_button.clicked.connect(self.accept)
        cancel_button = make_button("Vazgeç", "secondary")
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.import_button)

        class_row = QFormLayout()
        class_row.addRow("Hedef sınıf:", self.class_combo)

        layout = QVBoxLayout(self)
        layout.addLayout(class_row)
        layout.addWidget(summary)
        layout.addWidget(note)
        layout.addWidget(tabs, stretch=1)
        layout.addLayout(buttons)

    def selected_class_id(self) -> int | None:
        return self.class_combo.currentData()


class ImportWorker(QThread):
    """apply_student_import'u arka planda çalıştırır (40 öğrencinin şifre hash'i ~10 sn sürer)."""

    succeeded = Signal(int)   # eklenen öğrenci sayısı
    failed = Signal(str)      # Türkçe hata mesajı

    def __init__(self, rows: list[ImportRow], class_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows = rows
        self._class_id = class_id

    def run(self) -> None:
        try:
            self.succeeded.emit(import_export.apply_student_import(self._rows, self._class_id))
        except StudentAdminError as error:
            self.failed.emit(error.message)
        except Exception:  # noqa: BLE001 — arayüze ham hata gösterilmez, loga yazılır
            logger.exception("Öğrenci içe aktarma başarısız")
            self.failed.emit("Öğrenciler eklenirken beklenmeyen bir hata oluştu. Hiçbir öğrenci eklenmedi.")


def _table(headers: list[str], rows: list[list[object]]) -> QTableWidget:
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            table.setItem(r, c, QTableWidgetItem(str(value)))
    return table
