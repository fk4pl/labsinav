"""Kategori yönetimi penceresi: ekle, yeniden adlandır, sil. (Sahibi: B)

İçinde soru bulunan kategori silinemez; bu kuralı servis uygular, pencere sadece
gelen Türkçe hata mesajını kırmızı olarak gösterir.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.widgets import make_error_box, show_errors
from server.services import question_bank
from server.services.question_bank import CategoryRow, QuestionBankError


class CategoryDialog(QDialog):
    """Kapatıldıktan sonra self.changed True ise soru listesi yenilenmelidir."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.changed = False
        self.setWindowTitle("Kategoriler")
        self.resize(440, 480)

        title = QLabel("Kategoriler")
        title.setObjectName("title")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Yeni kategori adı")
        self.name_input.setMaxLength(question_bank.MAX_CATEGORY_NAME)
        self.name_input.returnPressed.connect(self._add)
        add_button = self._button("Ekle")
        add_button.clicked.connect(self._add)
        add_row = QHBoxLayout()
        add_row.addWidget(self.name_input, stretch=1)
        add_row.addWidget(add_button)

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._update_buttons)
        self.list_widget.itemDoubleClicked.connect(self._rename)

        self.rename_button = self._button("Yeniden adlandır", "secondary")
        self.rename_button.clicked.connect(self._rename)
        self.delete_button = self._button("Sil", "danger")
        self.delete_button.clicked.connect(self._delete)
        close_button = self._button("Kapat", "secondary")
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        self.error_box = make_error_box()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addLayout(add_row)
        layout.addWidget(self.list_widget, stretch=1)
        layout.addWidget(self.error_box)
        layout.addLayout(buttons)

        self._reload()

    @staticmethod
    def _button(text: str, object_name: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setAutoDefault(False)
        if object_name:
            button.setObjectName(object_name)
        return button

    def _reload(self, select_id: int | None = None) -> None:
        self.list_widget.clear()
        for category in question_bank.list_categories():
            item = QListWidgetItem(f"{category.name}   ({category.question_count} soru)")
            item.setData(Qt.ItemDataRole.UserRole, category)
            self.list_widget.addItem(item)
            if category.id == select_id:
                self.list_widget.setCurrentItem(item)
        self._update_buttons()

    def _selected(self) -> CategoryRow | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self) -> None:
        has_selection = self._selected() is not None
        self.rename_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    def _run(self, action, *args) -> object | None:
        """Servis fonksiyonunu çağırır; hata olursa kırmızı kutuda gösterir ve None döner."""
        show_errors(self.error_box, [])
        try:
            result = action(*args)
        except QuestionBankError as error:
            show_errors(self.error_box, [error.message])
            return None
        self.changed = True
        return result if result is not None else True

    def _add(self) -> None:
        new_id = self._run(question_bank.create_category, self.name_input.text())
        if new_id is not None:
            self.name_input.clear()
            self._reload(select_id=new_id)

    def _rename(self, *_) -> None:
        category = self._selected()
        if category is None:
            return
        name, ok = QInputDialog.getText(self, "Yeniden adlandır", "Yeni ad:", text=category.name)
        if ok and self._run(question_bank.rename_category, category.id, name) is not None:
            self._reload(select_id=category.id)

    def _delete(self) -> None:
        category = self._selected()
        if category is None:
            return
        answer = QMessageBox.question(self, "Kategori sil", f"'{category.name}' kategorisi silinsin mi?")
        if answer == QMessageBox.StandardButton.Yes and self._run(
            question_bank.delete_category, category.id
        ) is not None:
            self._reload()
