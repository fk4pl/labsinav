"""Sınavlar sekmesi: sınav listesi, oluştur/düzenle/çoğalt/sil ve başlat. (Sahibi: B)

- Sadece TASLAK sınav düzenlenir/silinir/başlatılır. Devam eden veya bitmiş sınav
  sadece görüntülenir ve çoğaltılabilir.
- Başlatma WsServer.start_exam ile yapılır (öğrencilere exam_start o gönderir). Başarılı
  olunca exam_started sinyali yayılır; ana pencere Canlı Panel'e geçer.
"""

import logging
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.exam_editor_dialog import ExamEditorDialog
from instructor_app.ui.widgets import format_points, make_button
from server.db.models import User
from server.net.ws_server import WsServer
from server.services import exam_admin
from server.services.exam_admin import STATUS_LABELS, ExamAdminError, ExamRow
from server.services.exam_session import ExamSessionError
from shared.theme import MUTED, PRIMARY, SUCCESS

logger = logging.getLogger(__name__)

COLUMNS = ["Sınav adı", "Sınıf", "Soru", "Toplam puan", "Süre", "Durum"]
COL_TITLE, COL_CLASS, COL_COUNT, COL_POINTS, COL_DURATION, COL_STATUS = range(len(COLUMNS))
ROW_ROLE = Qt.ItemDataRole.UserRole + 1

STATUS_COLORS = {"draft": MUTED, "running": PRIMARY, "finished": SUCCESS}


class ExamBuilderPage(QWidget):
    exam_started = Signal(int)  # exam_id

    def __init__(self, server: WsServer, user: User, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.server = server
        self.user = user

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_table(), stretch=1)
        layout.addLayout(self._build_buttons())
        self.reload()

    # --- Kurulum ---

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(self._open)
        return self.table

    def _build_buttons(self) -> QHBoxLayout:
        self.new_button = make_button("Yeni sınav")
        self.open_button = make_button("Düzenle", "secondary")
        self.duplicate_button = make_button("Çoğalt", "secondary")
        self.delete_button = make_button("Sil", "danger")
        self.start_button = make_button("▶ Başlat")
        self.count_label = QLabel()
        self.count_label.setObjectName("subtitle")

        self.new_button.clicked.connect(self._new)
        self.open_button.clicked.connect(self._open)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.delete_button.clicked.connect(self._delete)
        self.start_button.clicked.connect(self._start)

        row = QHBoxLayout()
        for button in (self.new_button, self.open_button, self.duplicate_button, self.delete_button):
            row.addWidget(button)
        row.addStretch()
        row.addWidget(self.count_label)
        row.addWidget(self.start_button)
        return row

    # --- Veriler ---

    def showEvent(self, event: QShowEvent) -> None:
        """Sekmeye her gelindiğinde liste tazelenir (ör. süre dolup sınav bitmiş olabilir)."""
        super().showEvent(event)
        self.reload()

    def reload(self, select_id: int | None = None) -> None:
        if select_id is None:
            selected = self._selected()
            select_id = selected.id if selected else None
        rows = exam_admin.list_exams()
        self.table.setRowCount(0)
        for row in rows:
            self._append_row(row)
        self._select(select_id)
        self.count_label.setText(f"{len(rows)} sınav")
        self._update_buttons()

    def _append_row(self, row: ExamRow) -> None:
        index = self.table.rowCount()
        self.table.insertRow(index)
        values = [
            row.title,
            row.class_name or "—",
            str(row.question_count),
            format_points(row.total_points),
            f"{row.duration_minutes} dk",
            STATUS_LABELS.get(row.status, row.status),
        ]
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setData(ROW_ROLE, row)
            self.table.setItem(index, column, item)
        status_item = self.table.item(index, COL_STATUS)
        status_item.setForeground(QBrush(QColor(STATUS_COLORS.get(row.status, MUTED))))
        font = status_item.font()
        font.setBold(True)
        status_item.setFont(font)

    def _selected(self) -> ExamRow | None:
        items = self.table.selectedItems()
        return items[0].data(ROW_ROLE) if items else None

    def _select(self, exam_id: int | None) -> None:
        for index in range(self.table.rowCount()):
            if self.table.item(index, 0).data(ROW_ROLE).id == exam_id:
                self.table.selectRow(index)
                return

    def _update_buttons(self) -> None:
        row = self._selected()
        is_draft = row is not None and row.status == "draft"
        self.open_button.setEnabled(row is not None)
        self.open_button.setText("Düzenle" if row is None or is_draft else "Görüntüle")
        self.duplicate_button.setEnabled(row is not None)
        self.delete_button.setEnabled(is_draft)
        self.start_button.setEnabled(is_draft)

    # --- İşlemler ---

    def _new(self) -> None:
        self._run_editor(None, read_only=False)

    def _open(self, *_) -> None:
        row = self._selected()
        if row is not None:
            self._run_editor(row.id, read_only=row.status != "draft")

    def _run_editor(self, exam_id: int | None, read_only: bool) -> None:
        try:
            dialog = ExamEditorDialog(exam_id, self.user.id, read_only, self)
        except ExamAdminError as error:  # bu arada silinmiş olabilir
            QMessageBox.warning(self, "Açılamadı", error.message)
            self.reload()
            return
        if dialog.exec() and dialog.saved_id is not None:
            self.reload(select_id=dialog.saved_id)
        dialog.deleteLater()

    def _duplicate(self) -> None:
        row = self._selected()
        if row is None:
            return
        new_id = self._call(exam_admin.duplicate_exam, row.id)
        if new_id is not None:
            self.reload(select_id=new_id)

    def _delete(self) -> None:
        row = self._selected()
        if row is None:
            return
        answer = QMessageBox.question(
            self, "Sınavı sil", f"“{row.title}” sınavı silinsin mi?",
            defaultButton=QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._call(exam_admin.delete_exam, row.id)
            self.reload()

    def _call(self, action, *args):
        """Servis fonksiyonunu çağırır; hata olursa Türkçe mesaj gösterip None döner."""
        try:
            return action(*args)
        except ExamAdminError as error:
            QMessageBox.warning(self, "İşlem yapılamadı", error.message)
            self.reload()
            return None

    # --- Başlatma ---

    def _start(self) -> None:
        row = self._selected()
        if row is None or row.status != "draft":
            return
        if not self._confirm_start(row):
            return
        try:
            self.server.start_exam(row.id)
        except ExamSessionError as error:
            QMessageBox.warning(self, "Sınav başlatılamadı", error.message)
            self.reload()
            return
        except Exception:
            logger.exception("Sınav başlatılırken beklenmeyen hata")
            QMessageBox.critical(
                self, "Sınav başlatılamadı",
                "Beklenmeyen bir hata oluştu. Sınavın durumunu listeden kontrol edin.",
            )
            self.reload()
            return
        self.reload(select_id=row.id)
        self.exam_started.emit(row.id)

    def _confirm_start(self, row: ExamRow) -> bool:
        class_size = next(
            (c.student_count for c in exam_admin.list_classes() if c.id == row.class_id), 0
        )
        connected = sum(1 for s in self.server.connected_students() if s.class_id == row.class_id)
        text = (
            f"<b>{escape(row.title)}</b><br><br>"
            f"Sınıf: {escape(row.class_name) or '—'}<br>"
            f"Bağlı öğrenci: <b>{connected} / {class_size}</b><br>"
            f"Soru: {row.question_count} · Toplam puan: {format_points(row.total_points)} · "
            f"Süre: {row.duration_minutes} dk<br><br>"
            "Sınav başlatılınca süre işlemeye başlar ve bağlı öğrencilerin ekranına gelir. "
            "Sonradan bağlanan öğrenciler girince sınava katılır.<br><br>Başlatılsın mı?"
        )
        box = QMessageBox(self)
        box.setWindowTitle("Sınavı başlat")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Question)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if connected < class_size:
            box.setInformativeText(f"Dikkat: {class_size - connected} öğrenci henüz bağlanmadı.")
        accepted = box.exec() == QMessageBox.StandardButton.Yes
        box.deleteLater()
        return accepted
