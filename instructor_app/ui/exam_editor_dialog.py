"""Sınav oluşturma/düzenleme penceresi. (Sahibi: B)

Düzen:
    [Ad] [Sınıf] [Süre]
    Solda soru bankası (filtreli)   |   Sağda sınavdaki sorular (sıra, puan)
    [Ekle →]                        |   [← Çıkar] [▲] [▼] [Rastgele N soru…]   Toplam: 80 puan

Sağdaki tablo "tek doğru kaynak"tır: Kaydet'e basınca satırlar sırayla okunup ExamDraft
oluşturulur ve kaydetme server/services/exam_admin.py'ye bırakılır.
Bitmiş veya devam eden sınav bu pencerede sadece GÖRÜNTÜLENİR (read_only=True).
"""

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QStyledItemDelegate,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.question_bank import ROW_ROLE, SORT_ROLE, QuestionFilterModel
from instructor_app.ui.widgets import format_points, make_button, make_error_box, show_errors
from server.services import exam_admin, question_bank
from server.services.exam_admin import (
    MAX_DURATION_MINUTES,
    ExamAdminError,
    ExamDetail,
    ExamDraft,
    ExamQuestionDraft,
)
from server.services.question_bank import MAX_POINTS, TYPE_LABELS, QuestionRow, turkish_lower

DEFAULT_DURATION = 40

BANK_COLUMNS = ["No", "Tür", "Kategori", "Soru", "Puan"]
BANK_TEXT_COLUMN = 3

EXAM_COLUMNS = ["Sıra", "Tür", "Soru", "Puan"]
COL_ORDER, COL_TYPE, COL_TEXT, COL_POINTS = range(len(EXAM_COLUMNS))
QUESTION_ID_ROLE = Qt.ItemDataRole.UserRole + 1


# ---------------------------------------------------------------------------
# Soru bankası tarafı
# ---------------------------------------------------------------------------

class BankFilterModel(QuestionFilterModel):
    """Soru Bankası sekmesindeki filtreye ek olarak, sınava zaten eklenmiş soruları gizler."""

    def __init__(self) -> None:
        super().__init__()
        self.hidden_ids: set[int] = set()

    def set_hidden_ids(self, ids: set[int]) -> None:
        self.beginFilterChange()
        self.hidden_ids = ids
        self.endFilterChange()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        row: QuestionRow = self.sourceModel().index(source_row, 0, source_parent).data(ROW_ROLE)
        if row.id in self.hidden_ids:
            return False
        return super().filterAcceptsRow(source_row, source_parent)


def _bank_items(row: QuestionRow) -> list[QStandardItem]:
    values = [
        (str(row.id), row.id),
        (TYPE_LABELS.get(row.type, row.type), row.type),
        (row.category_name or "—", turkish_lower(row.category_name)),
        (row.text_preview, turkish_lower(row.text_preview)),
        (format_points(row.default_points), row.default_points),
    ]
    items = []
    for text, sort_value in values:
        item = QStandardItem(text)
        item.setData(sort_value, SORT_ROLE)
        item.setData(row, ROW_ROLE)
        items.append(item)
    items[BANK_TEXT_COLUMN].setToolTip(row.text_preview)
    return items


# ---------------------------------------------------------------------------
# Puan hücresi düzenleyicisi
# ---------------------------------------------------------------------------

class PointsDelegate(QStyledItemDelegate):
    """Puan hücresine çift tıklayınca sayı kutusu açar; puanı '2,5' biçiminde gösterir."""

    def createEditor(self, parent: QWidget, option, index: QModelIndex) -> QWidget:
        spin = QDoubleSpinBox(parent)
        spin.setRange(0.5, MAX_POINTS)
        spin.setDecimals(1)
        spin.setSingleStep(1)
        return spin

    def displayText(self, value, locale) -> str:
        try:
            return format_points(float(value))
        except (TypeError, ValueError):
            return str(value)


# ---------------------------------------------------------------------------
# Rastgele soru seçme penceresi
# ---------------------------------------------------------------------------

class RandomPickDialog(QDialog):
    """Kategori ve soru sayısı sorar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rastgele soru ekle")
        self.category_combo = QComboBox()
        self.category_combo.addItem("Tüm kategoriler", None)
        for category in question_bank.list_categories():
            self.category_combo.addItem(f"{category.name} ({category.question_count})", category.id)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100)
        self.count_spin.setValue(5)

        form = QFormLayout()
        form.addRow("Kategori:", self.category_combo)
        form.addRow("Soru sayısı:", self.count_spin)
        cancel = make_button("Vazgeç", "secondary")
        cancel.clicked.connect(self.reject)
        ok = make_button("Ekle")
        ok.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def category_id(self) -> int | None:
        return self.category_combo.currentData()

    def count(self) -> int:
        return self.count_spin.value()


# ---------------------------------------------------------------------------
# Ana pencere
# ---------------------------------------------------------------------------

class ExamEditorDialog(QDialog):
    """exam_id=None → yeni sınav. read_only=True → sadece görüntüleme."""

    def __init__(
        self, exam_id: int | None, created_by: int | None,
        read_only: bool = False, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.exam_id = exam_id
        self.created_by = created_by
        self.read_only = read_only
        self.saved_id: int | None = None
        self.bank_rows: dict[int, QuestionRow] = {}

        self.setWindowTitle(self._window_title())
        self.resize(1200, 720)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_bank_panel())
        splitter.addWidget(self._build_exam_panel())
        splitter.setSizes([560, 640])
        if read_only:
            splitter.widget(0).hide()

        self.error_box = make_error_box()
        layout = QVBoxLayout(self)
        layout.addLayout(self._build_header())
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self.error_box)
        layout.addLayout(self._build_buttons())

        self._load_bank()
        self._fill(exam_admin.get_exam(exam_id) if exam_id is not None else None)
        self._apply_read_only()

    def _window_title(self) -> str:
        if self.exam_id is None:
            return "Yeni sınav"
        return "Sınavı görüntüle" if self.read_only else "Sınavı düzenle"

    # --- Kurulum ---

    def _build_header(self) -> QHBoxLayout:
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("ör. C Programlama — Vize")
        self.title_input.setMaxLength(exam_admin.MAX_TITLE_LENGTH)
        self.class_combo = QComboBox()
        self.class_combo.addItem("Sınıf seçin…", None)
        for school_class in exam_admin.list_classes():
            self.class_combo.addItem(
                f"{school_class.name} ({school_class.student_count} öğrenci)", school_class.id
            )
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, MAX_DURATION_MINUTES)
        self.duration_spin.setValue(DEFAULT_DURATION)
        self.duration_spin.setSuffix(" dk")

        row = QHBoxLayout()
        row.addWidget(QLabel("Sınav adı:"))
        row.addWidget(self.title_input, stretch=1)
        row.addWidget(QLabel("Sınıf:"))
        row.addWidget(self.class_combo)
        row.addWidget(QLabel("Süre:"))
        row.addWidget(self.duration_spin)
        return row

    def _build_bank_panel(self) -> QWidget:
        self.bank_model = QStandardItemModel(0, len(BANK_COLUMNS))
        self.bank_model.setHorizontalHeaderLabels(BANK_COLUMNS)
        self.bank_proxy = BankFilterModel()
        self.bank_proxy.setSourceModel(self.bank_model)

        self.category_filter = QComboBox()
        self.category_filter.addItem("Tüm kategoriler", None)
        for category in question_bank.list_categories():
            self.category_filter.addItem(category.name, category.id)
        self.type_filter = QComboBox()
        self.type_filter.addItem("Tüm türler", None)
        for value, label in TYPE_LABELS.items():
            self.type_filter.addItem(label, value)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Ara…")
        self.search_input.setClearButtonEnabled(True)
        self.category_filter.currentIndexChanged.connect(self._apply_bank_filters)
        self.type_filter.currentIndexChanged.connect(self._apply_bank_filters)
        self.search_input.textChanged.connect(self._apply_bank_filters)

        filters = QHBoxLayout()
        filters.addWidget(self.category_filter)
        filters.addWidget(self.type_filter)
        filters.addWidget(self.search_input, stretch=1)

        self.bank_table = QTableView()
        self.bank_table.setModel(self.bank_proxy)
        _setup_table(self.bank_table, BANK_TEXT_COLUMN)
        self.bank_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.bank_table.setSortingEnabled(True)
        self.bank_table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.bank_table.doubleClicked.connect(self._add_selected)

        self.add_button = make_button("Seçilenleri ekle →")
        self.add_button.clicked.connect(self._add_selected)
        hint = QLabel("Çift tıklayarak da ekleyebilirsiniz. Ctrl/Shift ile çoklu seçim.")
        hint.setObjectName("subtitle")
        bottom = QHBoxLayout()
        bottom.addWidget(hint, stretch=1)
        bottom.addWidget(self.add_button)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        title = QLabel("Soru bankası")
        title.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addLayout(filters)
        layout.addWidget(self.bank_table, stretch=1)
        layout.addLayout(bottom)
        return panel

    def _build_exam_panel(self) -> QWidget:
        self.exam_table = QTableWidget(0, len(EXAM_COLUMNS))
        self.exam_table.setHorizontalHeaderLabels(EXAM_COLUMNS)
        _setup_table(self.exam_table, COL_TEXT)
        self.exam_table.setItemDelegateForColumn(COL_POINTS, PointsDelegate(self.exam_table))
        self.exam_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.exam_table.itemChanged.connect(self._update_total)
        self.exam_table.itemSelectionChanged.connect(self._update_buttons)

        self.remove_button = make_button("← Çıkar", "secondary")
        self.up_button = make_button("▲ Yukarı", "secondary")
        self.down_button = make_button("▼ Aşağı", "secondary")
        self.random_button = make_button("Rastgele soru ekle…", "secondary")
        self.remove_button.clicked.connect(self._remove_selected)
        self.up_button.clicked.connect(self._move_up)
        self.down_button.clicked.connect(self._move_down)
        self.random_button.clicked.connect(self._add_random)
        self.total_label = QLabel()
        self.total_label.setStyleSheet("font-weight: 600;")

        buttons = QHBoxLayout()
        for button in (self.remove_button, self.up_button, self.down_button, self.random_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.total_label)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        title = QLabel("Sınavdaki sorular (puanı değiştirmek için puana çift tıklayın)")
        title.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(self.exam_table, stretch=1)
        layout.addLayout(buttons)
        return panel

    def _build_buttons(self) -> QHBoxLayout:
        self.cancel_button = make_button("Kapat" if self.read_only else "Vazgeç", "secondary")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = make_button("Kaydet")
        self.save_button.clicked.connect(self._save)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.cancel_button)
        row.addWidget(self.save_button)
        return row

    # --- Doldurma ---

    def _load_bank(self) -> None:
        for row in question_bank.list_questions():
            self.bank_rows[row.id] = row
            self.bank_model.appendRow(_bank_items(row))

    def _fill(self, detail: ExamDetail | None) -> None:
        if detail is not None:
            self.title_input.setText(detail.row.title)
            self.class_combo.setCurrentIndex(max(0, self.class_combo.findData(detail.row.class_id)))
            self.duration_spin.setValue(detail.row.duration_minutes)
            for question in detail.questions:
                self._append_question(
                    question.question_id, question.type, question.text_preview, question.points
                )
        self._after_change()
        self.title_input.setFocus()

    def _apply_read_only(self) -> None:
        if not self.read_only:
            return
        for widget in (self.title_input, self.class_combo, self.duration_spin):
            widget.setEnabled(False)
        for button in (self.remove_button, self.up_button, self.down_button,
                       self.random_button, self.save_button):
            button.hide()
        self.exam_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    # --- Soru ekleme / çıkarma / sıralama ---

    def _append_question(self, question_id: int, qtype: str, preview: str, points: float) -> None:
        row = self.exam_table.rowCount()
        self.exam_table.blockSignals(True)  # her hücre için toplam yeniden hesaplanmasın
        self.exam_table.insertRow(row)
        order_item = _readonly_item("")
        order_item.setData(QUESTION_ID_ROLE, question_id)
        text_item = _readonly_item(preview)
        text_item.setToolTip(preview)
        points_item = QTableWidgetItem()
        points_item.setData(Qt.ItemDataRole.EditRole, float(points))
        points_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.exam_table.setItem(row, COL_ORDER, order_item)
        self.exam_table.setItem(row, COL_TYPE, _readonly_item(TYPE_LABELS.get(qtype, qtype)))
        self.exam_table.setItem(row, COL_TEXT, text_item)
        self.exam_table.setItem(row, COL_POINTS, points_item)
        self.exam_table.blockSignals(False)

    def _add_rows(self, rows: list[QuestionRow]) -> None:
        for row in rows:
            self._append_question(row.id, row.type, row.text_preview, row.default_points)
        self._after_change()

    def _add_selected(self, *_) -> None:
        indexes = sorted(self.bank_table.selectionModel().selectedRows(), key=QModelIndex.row)
        self._add_rows([index.data(ROW_ROLE) for index in indexes])  # tablodaki görünüm sırasıyla

    def _add_random(self) -> None:
        dialog = RandomPickDialog(self)
        accepted = dialog.exec()
        category_id, count = dialog.category_id(), dialog.count()
        dialog.deleteLater()
        if not accepted:
            return
        picked = exam_admin.pick_random_questions(category_id, count, self.question_ids_set())
        if len(picked) < count:
            QMessageBox.information(
                self, "Yeterli soru yok",
                f"Bu kategoride sınavda olmayan {len(picked)} soru vardı; hepsi eklendi.",
            )
        self._add_rows(picked)

    def _remove_selected(self) -> None:
        for row in sorted(self._selected_exam_rows(), reverse=True):
            self.exam_table.removeRow(row)
        self._after_change()

    def _move_up(self) -> None:
        self._move_selected(-1)

    def _move_down(self) -> None:
        self._move_selected(+1)

    def _move_selected(self, step: int) -> None:
        """Seçili satırı bir yukarı (step=-1) veya aşağı (step=+1) taşır."""
        rows = self._selected_exam_rows()
        if len(rows) != 1:
            return
        row, target = rows[0], rows[0] + step
        if not 0 <= target < self.exam_table.rowCount():
            return
        self.exam_table.blockSignals(True)
        for column in range(self.exam_table.columnCount()):
            a = self.exam_table.takeItem(row, column)
            b = self.exam_table.takeItem(target, column)
            self.exam_table.setItem(row, column, b)
            self.exam_table.setItem(target, column, a)
        self.exam_table.blockSignals(False)
        self.exam_table.selectRow(target)
        self._after_change()

    def _selected_exam_rows(self) -> list[int]:
        return sorted({index.row() for index in self.exam_table.selectionModel().selectedRows()})

    # --- Durum güncelleme ---

    def _after_change(self) -> None:
        """Ekle/çıkar/taşı sonrası: sıra numaraları, gizlenen bankadaki sorular, toplam, butonlar."""
        self.exam_table.blockSignals(True)
        for row in range(self.exam_table.rowCount()):
            self.exam_table.item(row, COL_ORDER).setText(str(row + 1))
        self.exam_table.blockSignals(False)
        self.bank_proxy.set_hidden_ids(self.question_ids_set())
        self._update_total()
        self._update_buttons()

    def _update_total(self, *_) -> None:
        count = self.exam_table.rowCount()
        self.total_label.setText(f"Toplam: {format_points(self.total_points())} puan · {count} soru")

    def _update_buttons(self) -> None:
        selected = self._selected_exam_rows()
        self.remove_button.setEnabled(bool(selected))
        single = len(selected) == 1
        self.up_button.setEnabled(single and selected[0] > 0)
        self.down_button.setEnabled(single and selected[0] < self.exam_table.rowCount() - 1)

    def _apply_bank_filters(self) -> None:
        self.bank_proxy.set_filters(
            self.category_filter.currentData(),
            self.type_filter.currentData(),
            self.search_input.text(),
        )

    # --- Okuma (testler de kullanır) ---

    def question_ids(self) -> list[int]:
        return [
            self.exam_table.item(row, COL_ORDER).data(QUESTION_ID_ROLE)
            for row in range(self.exam_table.rowCount())
        ]

    def question_ids_set(self) -> set[int]:
        return set(self.question_ids())

    def points(self) -> list[float]:
        return [
            float(self.exam_table.item(row, COL_POINTS).data(Qt.ItemDataRole.EditRole))
            for row in range(self.exam_table.rowCount())
        ]

    def total_points(self) -> float:
        return sum(self.points())

    def build_draft(self) -> ExamDraft:
        return ExamDraft(
            title=self.title_input.text(),
            class_id=self.class_combo.currentData(),
            duration_minutes=self.duration_spin.value(),
            questions=[
                ExamQuestionDraft(qid, points)
                for qid, points in zip(self.question_ids(), self.points())
            ],
        )

    # --- Kaydetme ---

    def _save(self) -> None:
        draft = self.build_draft()
        errors = exam_admin.validate_exam_draft(draft)
        if not draft.questions:
            errors.append("Sınava en az bir soru ekleyin.")
        if errors:
            show_errors(self.error_box, errors)
            return
        try:
            if self.exam_id is None:
                self.saved_id = exam_admin.create_exam(draft, self.created_by)
            else:
                exam_admin.update_exam(self.exam_id, draft)
                self.saved_id = self.exam_id
        except ExamAdminError as error:
            show_errors(self.error_box, error.message.splitlines())
            return
        self.accept()


# ---------------------------------------------------------------------------
# Küçük yardımcılar
# ---------------------------------------------------------------------------

def _readonly_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _setup_table(table: QTableView, stretch_column: int) -> None:
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.verticalHeader().hide()
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
