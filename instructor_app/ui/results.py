"""Sonuçlar sekmesi. (Sahibi: D — P4)

Yukarıdan aşağıya:
  - Sınav seçici + "Yenile", "Yeniden puanla", "Excel'e Aktar" düğmeleri
  - Özet kartları: ortalama, medyan, en yüksek, en düşük, katılım
  - Alt sekmeler:
      "Öğrenciler"   → sıralanabilir tablo; çift tıklayınca öğrenci detayı açılır
      "Soru Analizi" → soru tablosu, başarı oranı grafiği, seçili test sorusunun şık dağılımı

Veriler server/services/results.py'den okunur; sekme her açıldığında yenilenir.
Puanlama gönderimden sonra arka planda yapıldığı için birkaç saniye "Puanlanıyor…" görünebilir.
"""

import re
from pathlib import Path

from PySide6.QtCore import QItemSelection, QModelIndex, QSortFilterProxyModel, QStandardPaths, Qt
from PySide6.QtGui import QBrush, QColor, QShowEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.bar_chart import Bar, BarChart
from instructor_app.ui.result_detail import StudentResultDialog, format_local_time
from instructor_app.ui.widgets import format_points
from server.services import grading, import_export, results
from server.services.grading import GradingError
from server.services.question_bank import TYPE_LABELS
from server.services.results import (
    STATUS_LABELS,
    ExamSummary,
    QuestionStat,
    ResultsError,
    StudentResultRow,
)
from shared.theme import DANGER, MUTED, SUCCESS

STUDENT_COLUMNS = ["Öğrenci No", "Ad Soyad", "Durum", "Puan", "Doğru", "Yanlış", "Boş",
                   "Gönderim", "Otomatik"]
QUESTION_COLUMNS = ["No", "Tür", "Soru", "Puan", "Doğru", "Yanlış", "Boş", "Doğru %", "Ort. Puan %"]

ROW_ROLE = Qt.ItemDataRole.UserRole + 1   # satırın veri nesnesi (StudentResultRow / QuestionStat)
SORT_ROLE = Qt.ItemDataRole.UserRole + 2  # sıralamada kullanılan değer (sayı/metin)

WARNING_COLOR = "#f59e0b"
OTHER_OPTION_COLOR = "#94a3b8"


def format_percent(rate: float | None) -> str:
    """0.675 → '%68' (Türkçede yüzde işareti başta yazılır)."""
    return "—" if rate is None else f"%{rate * 100:.0f}"


def rate_color(rate: float | None) -> str:
    """Başarı oranına göre renk: yüksek yeşil, orta turuncu, düşük kırmızı."""
    if rate is None:
        return MUTED
    if rate >= 0.7:
        return SUCCESS
    if rate >= 0.4:
        return WARNING_COLOR
    return DANGER


def make_item(text: str, sort_value: object = None, align_right: bool = False) -> QStandardItem:
    """Tablo hücresi. sort_value verilmezse metne göre sıralanır."""
    item = QStandardItem(text)
    item.setEditable(False)
    item.setData(text if sort_value is None else sort_value, SORT_ROLE)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def make_table(model: QStandardItemModel, stretch_column: int) -> tuple[QTableView, QSortFilterProxyModel]:
    """Başlığa tıklayınca sıralanan, sadece okunur tablo."""
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.setSortRole(SORT_ROLE)
    proxy.setSortLocaleAware(True)  # Türkçe harfler (ç, ğ, ı, ö, ş, ü) doğru sıralansın
    table = QTableView()
    table.setModel(proxy)
    table.setSortingEnabled(True)
    table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    return table, proxy


class SummaryCard(QFrame):
    """Üstteki küçük bilgi kartı: başlık + büyük değer."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        title_label = QLabel(title)
        title_label.setObjectName("subtitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("title")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class ResultsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addLayout(self._build_toolbar())
        layout.addLayout(self._build_cards())
        self.info_label = QLabel()
        self.info_label.setObjectName("subtitle")
        layout.addWidget(self.info_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_students_tab(), "Öğrenciler")
        self.tabs.addTab(self._build_questions_tab(), "Soru Analizi")
        layout.addWidget(self.tabs, stretch=1)
        self.exam_titles: dict[int, str] = {}
        self.show_empty()

    # ------------------------------------------------------------------
    # Arayüzün kurulması
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.exam_combo = QComboBox()
        self.exam_combo.setMinimumWidth(360)
        self.exam_combo.currentIndexChanged.connect(self.load_results)

        refresh_button = QPushButton("Yenile")
        refresh_button.setObjectName("secondary")
        refresh_button.clicked.connect(self.reload_exams)
        self.regrade_button = QPushButton("Yeniden puanla")
        self.regrade_button.setObjectName("secondary")
        self.regrade_button.clicked.connect(self.regrade)
        self.export_button = QPushButton("Excel'e Aktar")
        self.export_button.clicked.connect(self.export_excel)

        row.addWidget(QLabel("Sınav:"))
        row.addWidget(self.exam_combo)
        row.addStretch()
        row.addWidget(refresh_button)
        row.addWidget(self.regrade_button)
        row.addWidget(self.export_button)
        return row

    def _build_cards(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.average_card = SummaryCard("Ortalama")
        self.median_card = SummaryCard("Medyan")
        self.highest_card = SummaryCard("En yüksek")
        self.lowest_card = SummaryCard("En düşük")
        self.attendance_card = SummaryCard("Katılım")
        for card in (self.average_card, self.median_card, self.highest_card,
                     self.lowest_card, self.attendance_card):
            row.addWidget(card)
        return row

    def _build_students_tab(self) -> QWidget:
        self.student_model = QStandardItemModel(0, len(STUDENT_COLUMNS))
        self.student_model.setHorizontalHeaderLabels(STUDENT_COLUMNS)
        self.student_table, self.student_proxy = make_table(self.student_model, stretch_column=1)
        self.student_table.doubleClicked.connect(self.open_student_detail)

        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("Öğrencinin cevaplarını görmek ve klasik sorulara elle puan vermek için satıra çift tıklayın.")
        hint.setObjectName("subtitle")
        layout.addWidget(hint)
        layout.addWidget(self.student_table)
        return page

    def _build_questions_tab(self) -> QWidget:
        self.question_model = QStandardItemModel(0, len(QUESTION_COLUMNS))
        self.question_model.setHorizontalHeaderLabels(QUESTION_COLUMNS)
        self.question_table, self.question_proxy = make_table(self.question_model, stretch_column=2)
        self.question_table.selectionModel().selectionChanged.connect(self.on_question_selected)

        self.rate_chart = BarChart("Henüz puanlanmış kâğıt yok")
        self.option_chart = BarChart("Şık dağılımını görmek için tablodan bir test sorusu seçin")
        self.option_title = QLabel("Şık dağılımı")
        self.option_title.setObjectName("subtitle")

        charts = QHBoxLayout()
        charts.addLayout(self._titled("Doğru yapılma oranı", self._scrollable(self.rate_chart)), stretch=3)
        option_column = QVBoxLayout()
        option_column.addWidget(self.option_title)
        option_column.addWidget(self._scrollable(self.option_chart))
        charts.addLayout(option_column, stretch=2)
        chart_area = QWidget()
        chart_area.setLayout(charts)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.question_table)
        splitter.addWidget(chart_area)
        splitter.setSizes([260, 300])
        return splitter

    @staticmethod
    def _scrollable(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    @staticmethod
    def _titled(title: str, widget: QWidget) -> QVBoxLayout:
        column = QVBoxLayout()
        label = QLabel(title)
        label.setObjectName("subtitle")
        column.addWidget(label)
        column.addWidget(widget)
        return column

    # ------------------------------------------------------------------
    # Veri yükleme
    # ------------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        """Sekmeye her geçildiğinde güncel sonuçları göster."""
        super().showEvent(event)
        self.reload_exams()

    def current_exam_id(self) -> int | None:
        return self.exam_combo.currentData()

    def reload_exams(self) -> None:
        """Sınav listesini yeniden çeker; seçili sınav korunur."""
        selected = self.current_exam_id()
        self.exam_combo.blockSignals(True)  # doldururken load_results birçok kez çalışmasın
        self.exam_combo.clear()
        self.exam_titles = {}
        for exam in results.list_exams():
            self.exam_titles[exam.id] = exam.title
            state = "devam ediyor" if exam.status == "running" else format_local_time(exam.started_at)
            self.exam_combo.addItem(f"{exam.title} — {exam.class_name} ({state})", exam.id)
        index = self.exam_combo.findData(selected)
        self.exam_combo.setCurrentIndex(index if index >= 0 else 0)
        self.exam_combo.blockSignals(False)
        self.load_results()

    def load_results(self) -> None:
        exam_id = self.current_exam_id()
        if exam_id is None:
            self.show_empty()
            return
        try:
            summary = results.exam_summary(exam_id)
            rows = results.student_results(exam_id)
            stats = results.question_stats(exam_id)
        except ResultsError as error:
            QMessageBox.warning(self, "Sonuçlar", error.message)
            self.show_empty()
            return
        self.regrade_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.show_summary(summary)
        self.show_students(rows)
        self.show_questions(stats)

    def show_empty(self) -> None:
        self.regrade_button.setEnabled(False)
        self.export_button.setEnabled(False)
        for card in (self.average_card, self.median_card, self.highest_card,
                     self.lowest_card, self.attendance_card):
            card.set_value("—")
        self.info_label.setText("Henüz başlatılmış bir sınav yok.")
        self.student_model.setRowCount(0)
        self.question_model.setRowCount(0)
        self.rate_chart.set_bars([])
        self.option_chart.set_bars([])

    def show_summary(self, summary: ExamSummary) -> None:
        def points(value: float | None) -> str:
            return "—" if value is None else format_points(round(value, 2))

        self.average_card.set_value(points(summary.average))
        self.median_card.set_value(points(summary.median))
        self.highest_card.set_value(points(summary.highest))
        self.lowest_card.set_value(points(summary.lowest))
        self.attendance_card.set_value(f"{summary.participant_count} / {summary.expected_count}")

        parts = [f"Tam puan: {format_points(summary.max_score)}",
                 f"Standart sapma: {points(summary.std_dev)}"]
        waiting = summary.participant_count - summary.graded_count
        if waiting:
            parts.append(f"{waiting} kâğıt puanlanıyor — birkaç saniye sonra Yenile'ye basın")
        self.info_label.setText("   •   ".join(parts))

    def show_students(self, rows: list[StudentResultRow]) -> None:
        self.student_model.setRowCount(0)
        for row in rows:
            self.student_model.appendRow(self._student_items(row))

    @staticmethod
    def _student_items(row: StudentResultRow) -> list[QStandardItem]:
        attended = row.submission_id is not None
        if row.status == "submitted":
            score_text = "Puanlanıyor…" if row.score is None else format_points(row.score)
        else:
            score_text = "—"

        def count(value: int) -> QStandardItem:
            return make_item(str(value) if attended else "—", value if attended else -1, align_right=True)

        items = [
            make_item(row.student_no),
            make_item(row.full_name),
            make_item(STATUS_LABELS[row.status]),
            make_item(score_text, -1 if row.score is None else row.score, align_right=True),
            count(row.correct),
            count(row.wrong),
            count(row.blank),
            make_item(format_local_time(row.submitted_at),
                      row.submitted_at.timestamp() if row.submitted_at else 0),
            make_item(("Evet" if row.auto_submitted else "Hayır") if row.submitted_at else "—"),
        ]
        items[0].setData(row, ROW_ROLE)
        if row.status != "submitted":
            for item in items:
                item.setForeground(QBrush(QColor(MUTED)))
        return items

    def show_questions(self, stats: list[QuestionStat]) -> None:
        self.question_model.setRowCount(0)
        for stat in stats:
            self.question_model.appendRow(self._question_items(stat))
        self.rate_chart.set_bars([
            Bar(f"Soru {s.order}", s.correct_rate or 0.0, format_percent(s.correct_rate),
                rate_color(s.correct_rate))
            for s in stats
        ])
        self.option_title.setText("Şık dağılımı")
        self.option_chart.set_bars([])

    @staticmethod
    def _question_items(stat: QuestionStat) -> list[QStandardItem]:
        rate_item = make_item(format_percent(stat.correct_rate), stat.correct_rate or 0.0, align_right=True)
        rate_item.setForeground(QBrush(QColor(rate_color(stat.correct_rate))))
        items = [
            make_item(str(stat.order), stat.order, align_right=True),
            make_item(TYPE_LABELS.get(stat.question_type, stat.question_type)),
            make_item(" ".join(stat.text.split())),  # satır sonları tabloda tek satır olsun
            make_item(format_points(stat.max_points), stat.max_points, align_right=True),
            make_item(str(stat.correct), stat.correct, align_right=True),
            make_item(str(stat.wrong), stat.wrong, align_right=True),
            make_item(str(stat.blank), stat.blank, align_right=True),
            rate_item,
            make_item(format_percent(stat.average_rate), stat.average_rate or 0.0, align_right=True),
        ]
        items[0].setData(stat, ROW_ROLE)
        return items

    # ------------------------------------------------------------------
    # Kullanıcı işlemleri
    # ------------------------------------------------------------------

    def _row_data(self, proxy: QSortFilterProxyModel, index: QModelIndex) -> object:
        """Tablodaki (sıralanmış) satırın veri nesnesini döner."""
        source = proxy.mapToSource(index)
        return proxy.sourceModel().index(source.row(), 0).data(ROW_ROLE)

    def on_question_selected(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        indexes = selected.indexes()
        stat: QuestionStat | None = self._row_data(self.question_proxy, indexes[0]) if indexes else None
        if stat is None or not stat.options:
            self.option_title.setText("Şık dağılımı (sadece test sorularında)")
            self.option_chart.set_bars([])
            return
        answered = stat.correct + stat.wrong + stat.blank
        self.option_title.setText(f"Soru {stat.order} — şık dağılımı (doğru şık yeşil)")
        self.option_chart.set_bars([
            Bar(f"{o.letter}) {o.text}", o.count / answered if answered else 0.0,
                f"{o.count} kişi", SUCCESS if o.is_correct else OTHER_OPTION_COLOR)
            for o in stat.options
        ])

    def open_student_detail(self, index: QModelIndex) -> None:
        row: StudentResultRow = self._row_data(self.student_proxy, index)
        if row.submission_id is None:
            QMessageBox.information(self, "Sonuçlar", f"{row.full_name} bu sınava girmedi.")
            return
        try:
            dialog = StudentResultDialog(row.submission_id, self)
        except ResultsError as error:
            QMessageBox.warning(self, "Sonuçlar", error.message)
            return
        dialog.exec()
        if dialog.changed:
            self.load_results()
        dialog.deleteLater()

    def regrade(self) -> None:
        exam_id = self.current_exam_id()
        if exam_id is None:
            return
        answer = QMessageBox.question(
            self, "Yeniden puanla",
            "Gönderilmiş tüm kâğıtlar cevap anahtarına göre yeniden puanlanacak.\n"
            "Elle verdiğiniz puanlar korunur. Devam edilsin mi?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            count = grading.regrade_exam(exam_id)
        except GradingError as error:
            QMessageBox.warning(self, "Yeniden puanla", error.message)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.load_results()
        QMessageBox.information(self, "Yeniden puanla", f"{count} kâğıt yeniden puanlandı.")

    def export_excel(self) -> None:
        exam_id = self.current_exam_id()
        if exam_id is None:
            return
        path = self._ask_save_path()
        if path is None:
            return
        try:
            import_export.export_results_xlsx(exam_id, path)
        except OSError:
            QMessageBox.warning(
                self, "Excel'e Aktar",
                "Dosya kaydedilemedi. Dosya Excel'de açıksa kapatıp tekrar deneyin "
                "veya başka bir klasör seçin.",
            )
            return
        QMessageBox.information(self, "Excel'e Aktar", f"Sonuçlar kaydedildi:\n{path}")

    def _ask_save_path(self) -> Path | None:
        title = self.exam_titles.get(self.current_exam_id(), "")
        safe_title = re.sub(r"[^\w\- ]+", "_", title).strip() or "Sinav"
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        suggested = str(Path(folder) / f"{safe_title} - Sonuçlar.xlsx")
        chosen, _ = QFileDialog.getSaveFileName(self, "Excel'e Aktar", suggested, "Excel dosyası (*.xlsx)")
        if not chosen:
            return None
        path = Path(chosen)
        return path if path.suffix.lower() == ".xlsx" else path.with_suffix(".xlsx")
