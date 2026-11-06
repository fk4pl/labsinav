"""Soru Bankası sekmesi: soru listesi, filtreler ve soru işlemleri. (Sahibi: B)

Liste veri tabanından bir kez çekilir (list_questions). Kategori/tür/arama filtreleri
tablonun üstündeki "proxy" modelde anlık uygulanır; her tuşa basışta sorgu yapılmaz.
Ekle/düzenle/sil gibi bir işlemden sonra liste yeniden çekilir.
"""

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.category_dialog import CategoryDialog
from instructor_app.ui.question_dialog import QuestionDialog
from instructor_app.ui.question_preview import QuestionPreviewDialog
from instructor_app.ui.widgets import format_points
from server.services import question_bank
from server.services.question_bank import TYPE_LABELS, QuestionBankError, QuestionRow, turkish_lower
from shared.theme import MUTED

COLUMNS = ["No", "Tür", "Kategori", "Soru", "Puan", "Son düzenleme"]
COL_ID, COL_TYPE, COL_CATEGORY, COL_TEXT, COL_POINTS, COL_UPDATED = range(len(COLUMNS))

ROW_ROLE = Qt.ItemDataRole.UserRole + 1   # satırın QuestionRow nesnesi
SORT_ROLE = Qt.ItemDataRole.UserRole + 2  # sıralamada kullanılan değer (sayı/tarih)


class QuestionFilterModel(QSortFilterProxyModel):
    """Kategori, tür ve metin aramasına göre satırları gizler/gösterir."""

    def __init__(self) -> None:
        super().__init__()
        self.category_id: int | None = None
        self.question_type: str | None = None
        self.search = ""
        self.setSortRole(SORT_ROLE)

    def set_filters(self, category_id: int | None, question_type: str | None, search: str) -> None:
        self.beginFilterChange()  # Qt'ye "filtre değişiyor" de; bitince liste yenilenir
        self.category_id = category_id
        self.question_type = question_type
        self.search = turkish_lower(search.strip())
        self.endFilterChange()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        index = self.sourceModel().index(source_row, 0, source_parent)
        row: QuestionRow = index.data(ROW_ROLE)
        if self.category_id is not None and row.category_id != self.category_id:
            return False
        if self.question_type is not None and row.type != self.question_type:
            return False
        return not self.search or self.search in turkish_lower(row.text)


class QuestionBankPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.proxy = QuestionFilterModel()
        self.proxy.setSourceModel(self.model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(self._build_filters())
        layout.addWidget(self._build_table(), stretch=1)
        layout.addLayout(self._build_buttons())

        self.reload_categories()
        self.reload()

    # --- Kurulum ---

    def _build_filters(self) -> QHBoxLayout:
        self.category_filter = QComboBox()
        self.category_filter.setMinimumWidth(180)
        self.type_filter = QComboBox()
        self.type_filter.addItem("Tüm türler", None)
        for value, label in TYPE_LABELS.items():
            self.type_filter.addItem(label, value)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Soru metninde ara…")
        self.search_input.setClearButtonEnabled(True)
        self.archived_check = QCheckBox("Arşivlenenleri göster")
        categories_button = QPushButton("Kategoriler…")
        categories_button.setObjectName("secondary")
        categories_button.clicked.connect(self._manage_categories)

        self.category_filter.currentIndexChanged.connect(self._apply_filters)
        self.type_filter.currentIndexChanged.connect(self._apply_filters)
        self.search_input.textChanged.connect(self._apply_filters)
        self.archived_check.toggled.connect(self._on_archived_toggled)

        row = QHBoxLayout()
        row.addWidget(QLabel("Kategori:"))
        row.addWidget(self.category_filter)
        row.addWidget(QLabel("Tür:"))
        row.addWidget(self.type_filter)
        row.addWidget(self.search_input, stretch=1)
        row.addWidget(self.archived_check)
        row.addWidget(categories_button)
        return row

    def _build_table(self) -> QTableView:
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.sortByColumn(COL_UPDATED, Qt.SortOrder.DescendingOrder)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)

        self.table.doubleClicked.connect(self._edit)
        self.table.selectionModel().selectionChanged.connect(self._update_buttons)
        return self.table

    def _build_buttons(self) -> QHBoxLayout:
        self.new_button = QPushButton("Yeni soru")
        self.edit_button = self._secondary("Düzenle")
        self.duplicate_button = self._secondary("Çoğalt")
        self.preview_button = self._secondary("Önizle")
        self.delete_button = QPushButton("Sil")
        self.delete_button.setObjectName("danger")
        self.restore_button = self._secondary("Arşivden çıkar")
        self.count_label = QLabel()
        self.count_label.setObjectName("subtitle")

        self.new_button.clicked.connect(self._new)
        self.edit_button.clicked.connect(self._edit)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.preview_button.clicked.connect(self._preview)
        self.delete_button.clicked.connect(self._delete)
        self.restore_button.clicked.connect(self._restore)

        row = QHBoxLayout()
        row.addWidget(self.new_button)
        row.addWidget(self.edit_button)
        row.addWidget(self.duplicate_button)
        row.addWidget(self.preview_button)
        row.addWidget(self.delete_button)
        row.addWidget(self.restore_button)
        row.addStretch()
        row.addWidget(self.count_label)
        return row

    @staticmethod
    def _secondary(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("secondary")
        return button

    # --- Verileri yükleme ---

    def reload_categories(self) -> None:
        """Kategori filtresini yeniden doldurur; seçili kategori korunur."""
        current = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Tüm kategoriler", None)
        self.categories = question_bank.list_categories()
        for category in self.categories:
            self.category_filter.addItem(category.name, category.id)
        self.category_filter.setCurrentIndex(max(0, self.category_filter.findData(current)))
        self.category_filter.blockSignals(False)
        self._apply_filters()

    def reload(self, select_id: int | None = None) -> None:
        """Soruları veri tabanından tekrar çeker. select_id verilirse o satır seçilir."""
        if select_id is None:
            select_id = self._selected_id()
        rows = question_bank.list_questions(include_archived=self.archived_check.isChecked())
        self.model.removeRows(0, self.model.rowCount())
        for row in rows:
            self.model.appendRow(_make_items(row))
        self._select(select_id)
        self._update_buttons()

    def _on_archived_toggled(self, _checked: bool) -> None:
        self.reload()

    def _apply_filters(self) -> None:
        self.proxy.set_filters(
            self.category_filter.currentData(),
            self.type_filter.currentData(),
            self.search_input.text(),
        )
        self._update_buttons()

    # --- Seçim ---

    def _selected_row(self) -> QuestionRow | None:
        indexes = self.table.selectionModel().selectedRows()
        return indexes[0].data(ROW_ROLE) if indexes else None

    def _selected_id(self) -> int | None:
        row = self._selected_row()
        return row.id if row else None

    def _select(self, question_id: int | None) -> None:
        if question_id is None:
            return
        for proxy_row in range(self.proxy.rowCount()):
            index = self.proxy.index(proxy_row, 0)
            if index.data(ROW_ROLE).id == question_id:
                self.table.selectRow(proxy_row)
                self.table.scrollTo(index)
                return

    def _update_buttons(self, *_) -> None:
        row = self._selected_row()
        has_selection = row is not None
        for button in (self.edit_button, self.duplicate_button, self.preview_button):
            button.setEnabled(has_selection)
        is_archived = has_selection and row.is_archived
        self.delete_button.setVisible(not is_archived)
        self.delete_button.setEnabled(has_selection)
        self.restore_button.setVisible(is_archived)
        self.count_label.setText(f"{self.proxy.rowCount()} / {self.model.rowCount()} soru")

    # --- İşlemler ---

    def _new(self) -> None:
        dialog = QuestionDialog(self.categories, parent=self)
        accepted = dialog.exec()
        dialog.deleteLater()
        if accepted:
            self.reload(select_id=dialog.saved_id)

    def _edit(self, *_) -> None:
        question_id = self._selected_id()
        if question_id is None:
            return
        detail = self._call(question_bank.get_question, question_id)
        if detail is None:
            return
        dialog = QuestionDialog(self.categories, detail, parent=self)
        accepted = dialog.exec()
        dialog.deleteLater()
        if accepted:
            self.reload(select_id=dialog.saved_id)
        elif dialog.wants_duplicate:
            self._duplicate(open_editor=True)

    def _duplicate(self, open_editor: bool = False) -> None:
        question_id = self._selected_id()
        if question_id is None:
            return
        new_id = self._call(question_bank.duplicate_question, question_id)
        if new_id is None:
            return
        self.reload(select_id=new_id)
        if open_editor:
            self._edit()

    def _preview(self) -> None:
        question_id = self._selected_id()
        if question_id is None:
            return
        question = self._call(question_bank.preview_question, question_id)
        if question is not None:
            dialog = QuestionPreviewDialog(question, parent=self)
            dialog.exec()
            dialog.deleteLater()

    def _delete(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        answer = QMessageBox.question(
            self, "Soru sil",
            f"{row.id} numaralı soru silinsin mi?\n\n\"{row.text_preview}\"",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self._call(question_bank.delete_question, row.id)
        if result == "archived":
            QMessageBox.information(
                self, "Soru arşivlendi",
                "Bu soru daha önce bir sınavda kullanıldığı için silinmedi, arşivlendi.\n\n"
                "Eski sınav sonuçları korunur; soru yeni sınavlara eklenemez.\n"
                "Görmek için \"Arşivlenenleri göster\" kutusunu işaretleyin.",
            )
        self.reload()

    def _restore(self) -> None:
        question_id = self._selected_id()
        if question_id is None:
            return
        try:
            question_bank.restore_question(question_id)
        except QuestionBankError as error:
            QMessageBox.warning(self, "İşlem yapılamadı", error.message)
        self.reload(select_id=question_id)

    def _manage_categories(self) -> None:
        dialog = CategoryDialog(parent=self)
        dialog.exec()
        dialog.deleteLater()
        if dialog.changed:
            self.reload_categories()
            self.reload()  # kategori adı değişmiş olabilir

    def _call(self, action, *args):
        """Servis fonksiyonunu çağırır. Hata olursa Türkçe mesaj kutusu gösterir ve None döner.

        (Ör. soru bu arada başka bir pencereden silinmişse "Soru bulunamadı" gösterilir.)
        """
        try:
            return action(*args)
        except QuestionBankError as error:
            QMessageBox.warning(self, "İşlem yapılamadı", error.message)
            self.reload()
            return None


# ---------------------------------------------------------------------------
# Tablo satırı oluşturma
# ---------------------------------------------------------------------------

def _make_items(row: QuestionRow) -> list[QStandardItem]:
    local_time = row.updated_at.astimezone()  # UTC → bilgisayarın yerel saati
    values = [
        (str(row.id), row.id),
        (TYPE_LABELS.get(row.type, row.type), row.type),
        (row.category_name or "—", turkish_lower(row.category_name)),
        (row.text_preview, turkish_lower(row.text_preview)),
        (format_points(row.default_points), row.default_points),
        (local_time.strftime("%d.%m.%Y %H:%M"), local_time.timestamp()),
    ]
    items = []
    for text, sort_value in values:
        item = QStandardItem(text)
        item.setData(sort_value, SORT_ROLE)
        item.setData(row, ROW_ROLE)
        if row.is_archived:
            _style_archived(item)
        items.append(item)
    items[COL_TEXT].setToolTip(row.text_preview)
    items[COL_ID].setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    items[COL_POINTS].setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if row.is_archived:
        items[COL_TEXT].setText(f"[Arşiv] {row.text_preview}")
    return items


def _style_archived(item: QStandardItem) -> None:
    item.setForeground(QBrush(QColor(MUTED)))
