"""Loglar sekmesi: olay kaydı listesi, filtreler, dışa aktarma. (Sahibi: B)

Veriler event_logs tablosundan server/services/event_query.py ile okunur.
Filtre değişince liste hemen yeniden çekilir (sorgu hızlıdır, en fazla 5000 satır).
"""

import logging

from PySide6.QtCore import QDateTime, QTime, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.widgets import format_local, make_button
from server.services import event_query, exam_admin
from server.services.event_log import Event
from server.services.event_query import DEFAULT_LIMIT, EVENT_LABELS, EventFilter, EventRow
from shared import config
from shared.theme import DANGER, MUTED, PRIMARY, SUCCESS

logger = logging.getLogger(__name__)

COLUMNS = ["Zaman", "Olay", "Öğrenci", "Sınav", "IP", "Ayrıntı"]
COL_TIME, COL_EVENT, COL_USER, COL_EXAM, COL_IP, COL_DETAIL = range(len(COLUMNS))

WARNING_COLOR = "#d97706"
EVENT_COLORS = {
    Event.LOGIN_FAILED: DANGER,
    Event.REJECTED_LATE: DANGER,
    Event.DUPLICATE_SESSION: DANGER,
    Event.FOCUS_LOST: WARNING_COLOR,
    Event.DISCONNECTED: WARNING_COLOR,
    Event.SUBMITTED: SUCCESS,
    Event.AUTO_SUBMITTED: SUCCESS,
    Event.EXAM_STARTED: PRIMARY,
    Event.EXAM_STOPPED: PRIMARY,
    Event.EXAM_EXTENDED: PRIMARY,
    Event.LOGIN: MUTED,
}

ALL_STUDENTS = "Tüm öğrenciler"


class LogsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[EventRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(self._build_filters())
        layout.addLayout(self._build_date_filters())
        layout.addWidget(self._build_table(), stretch=1)
        layout.addLayout(self._build_buttons())

    # --- Kurulum ---

    def _build_filters(self) -> QHBoxLayout:
        self.exam_filter = QComboBox()
        self.exam_filter.setMinimumWidth(220)
        self.user_filter = QComboBox()
        self.user_filter.setEditable(True)  # öğrenci no yazılarak da aranabilir
        self.user_filter.setMinimumWidth(160)
        self.event_filter = QComboBox()
        self.event_filter.addItem("Tüm olaylar", None)
        for event, label in EVENT_LABELS.items():
            self.event_filter.addItem(label, event)

        self.exam_filter.currentIndexChanged.connect(self.reload)
        self.user_filter.currentIndexChanged.connect(self.reload)
        self.user_filter.lineEdit().editingFinished.connect(self.reload)
        self.event_filter.currentIndexChanged.connect(self.reload)

        row = QHBoxLayout()
        row.addWidget(QLabel("Sınav:"))
        row.addWidget(self.exam_filter)
        row.addWidget(QLabel("Öğrenci:"))
        row.addWidget(self.user_filter)
        row.addWidget(QLabel("Olay:"))
        row.addWidget(self.event_filter)
        row.addStretch()
        return row

    def _build_date_filters(self) -> QHBoxLayout:
        self.date_check = QCheckBox("Tarih aralığı:")
        today = QDateTime.currentDateTime()
        self.date_from = _datetime_edit(QDateTime(today.date(), QTime(0, 0)))
        self.date_to = _datetime_edit(QDateTime(today.date(), QTime(23, 59, 59)))
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)

        self.date_check.toggled.connect(self._on_date_toggled)
        self.date_from.dateTimeChanged.connect(self.reload)
        self.date_to.dateTimeChanged.connect(self.reload)
        refresh_button = make_button("Yenile", "secondary")
        refresh_button.clicked.connect(self.reload)

        row = QHBoxLayout()
        row.addWidget(self.date_check)
        row.addWidget(self.date_from)
        row.addWidget(QLabel("–"))
        row.addWidget(self.date_to)
        row.addStretch()
        row.addWidget(refresh_button)
        return row

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_DETAIL, QHeaderView.ResizeMode.Stretch)
        return self.table

    def _build_buttons(self) -> QHBoxLayout:
        open_button = make_button("Log dosyasını aç", "secondary")
        csv_button = make_button("CSV'ye aktar", "secondary")
        excel_button = make_button("Excel'e aktar", "secondary")
        open_button.clicked.connect(self._open_log_file)
        csv_button.clicked.connect(self._export_csv)
        excel_button.clicked.connect(self._export_excel)
        self.count_label = QLabel()
        self.count_label.setObjectName("subtitle")

        row = QHBoxLayout()
        row.addWidget(open_button)
        row.addStretch()
        row.addWidget(self.count_label)
        row.addWidget(csv_button)
        row.addWidget(excel_button)
        return row

    # --- Filtre seçenekleri ---

    def showEvent(self, event: QShowEvent) -> None:
        """Sekmeye her gelindiğinde seçenekler ve liste tazelenir."""
        super().showEvent(event)
        self._reload_choices()
        self.reload()

    def _reload_choices(self) -> None:
        """Sınav ve öğrenci seçeneklerini yeniden doldurur; mevcut seçim korunur."""
        current_exam = self.exam_filter.currentData()
        current_user = self.user_filter.currentText()
        for combo in (self.exam_filter, self.user_filter):
            combo.blockSignals(True)
            combo.clear()

        self.exam_filter.addItem("Tüm sınavlar", None)
        for exam in exam_admin.list_exams():
            self.exam_filter.addItem(exam.title, exam.id)
        self.exam_filter.setCurrentIndex(max(0, self.exam_filter.findData(current_exam)))

        self.user_filter.addItem(ALL_STUDENTS)
        self.user_filter.addItems(event_query.list_event_usernames())
        self.user_filter.setCurrentText(current_user or ALL_STUDENTS)

        for combo in (self.exam_filter, self.user_filter):
            combo.blockSignals(False)

    def _on_date_toggled(self, checked: bool) -> None:
        self.date_from.setEnabled(checked)
        self.date_to.setEnabled(checked)
        self.reload()

    def current_filter(self) -> EventFilter:
        username = self.user_filter.currentText().strip()
        filters = EventFilter(
            exam_id=self.exam_filter.currentData(),
            username=None if username in ("", ALL_STUDENTS) else username,
            event=self.event_filter.currentData(),
        )
        if self.date_check.isChecked():
            # QDateTime → saat dilimli Python datetime (yerel saat; veri tabanı UTC'ye çevirir)
            filters.date_from = self.date_from.dateTime().toPython().astimezone()
            filters.date_to = self.date_to.dateTime().toPython().astimezone()
        return filters

    # --- Liste ---

    def reload(self, *_) -> None:
        self.rows = event_query.list_events(self.current_filter())
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            self._fill_row(index, row)
        suffix = f" (en yeni {DEFAULT_LIMIT} gösteriliyor)" if len(self.rows) >= DEFAULT_LIMIT else ""
        self.count_label.setText(f"{len(self.rows)} olay{suffix}")

    def _fill_row(self, index: int, row: EventRow) -> None:
        values = [
            format_local(row.at, "%d.%m.%Y %H:%M:%S"),
            event_query.event_label(row.event),
            row.username or "",
            row.exam_title or (str(row.exam_id) if row.exam_id else ""),
            row.ip or "",
            row.detail or "",
        ]
        for column, text in enumerate(values):
            self.table.setItem(index, column, QTableWidgetItem(text))
        event_item = self.table.item(index, COL_EVENT)
        event_item.setForeground(QBrush(QColor(EVENT_COLORS.get(row.event, MUTED))))
        font = event_item.font()
        font.setBold(True)
        event_item.setFont(font)
        self.table.item(index, COL_DETAIL).setToolTip(row.detail or "")

    # --- Dosya işlemleri ---

    def _open_log_file(self) -> None:
        path = config.EVENTS_LOG_PATH
        if not path.exists():
            QMessageBox.information(self, "Log dosyası", "Henüz log dosyası oluşmadı.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Log dosyası", f"Dosya açılamadı. Konumu:\n{path}")

    def _export_csv(self) -> None:
        self._export("CSV'ye aktar", "olaylar.csv", "CSV dosyası (*.csv)", event_query.export_events_csv)

    def _export_excel(self) -> None:
        self._export("Excel'e aktar", "olaylar.xlsx", "Excel dosyası (*.xlsx)", event_query.export_events_xlsx)

    def _export(self, title: str, default_name: str, file_filter: str, writer) -> None:
        if not self.rows:
            QMessageBox.information(self, title, "Aktarılacak olay yok.")
            return
        path, _ = QFileDialog.getSaveFileName(self, title, default_name, file_filter)
        if not path:
            return
        try:
            writer(self.rows, path)
        except OSError:
            logger.exception("Log dışa aktarılamadı: %s", path)
            QMessageBox.warning(
                self, title, "Dosya kaydedilemedi. Dosya başka bir programda açık olabilir."
            )
            return
        QMessageBox.information(self, title, f"{len(self.rows)} olay kaydedildi:\n{path}")


def _datetime_edit(value: QDateTime) -> QDateTimeEdit:
    edit = QDateTimeEdit(value)
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy HH:mm")
    return edit
