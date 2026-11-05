"""Soru ekleme/düzenleme penceresi. (Sahibi: B)

Pencere kullanıcının girdiklerinden bir QuestionDraft oluşturur ve kaydetmeyi
server/services/question_bank.py'ye bırakır. Doğrulama hataları pencerenin altında
kırmızı kutuda gösterilir; hata varken pencere kapanmaz.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.question_preview import looks_like_code
from instructor_app.ui.widgets import make_error_box, set_monospace, show_errors
from server.services import question_bank
from server.services.question_bank import (
    MAX_OPTIONS,
    MAX_POINTS,
    MIN_OPTIONS,
    CategoryRow,
    OptionDraft,
    QuestionBankError,
    QuestionDetail,
    QuestionDraft,
)

OPTION_LETTERS = "ABCDEF"
DEFAULT_OPTION_COUNT = 4


def _button(text: str, object_name: str = "") -> QPushButton:
    """Enter tuşuna basınca yanlışlıkla tıklanmayan buton."""
    button = QPushButton(text)
    button.setAutoDefault(False)
    if object_name:
        button.setObjectName(object_name)
    return button


# ---------------------------------------------------------------------------
# Test (çoktan seçmeli) şıkları
# ---------------------------------------------------------------------------

class _OptionRow(QWidget):
    """Bir şık satırı: [doğru mu? (radio)] [harf] [metin] [sil]."""

    delete_requested = Signal(object)  # bu satır (_OptionRow)

    def __init__(self, group: QButtonGroup) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.radio = QRadioButton()
        self.radio.setToolTip("Doğru şık")
        group.addButton(self.radio)
        self.letter = QLabel()
        self.letter.setFixedWidth(18)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Şık metni")
        self.delete_button = _button("Sil", "secondary")
        self.delete_button.setToolTip("Bu şıkkı sil")
        self.delete_button.clicked.connect(self._emit_delete)
        layout.addWidget(self.radio)
        layout.addWidget(self.letter)
        layout.addWidget(self.text_input, stretch=1)
        layout.addWidget(self.delete_button)

    def _emit_delete(self) -> None:
        self.delete_requested.emit(self)


class McqEditor(QWidget):
    """2-6 şık; tam olarak bir tanesi doğru işaretlenir (radio)."""

    def __init__(self) -> None:
        super().__init__()
        self.group = QButtonGroup(self)  # aynı anda sadece bir radio seçili olabilir
        self.rows: list[_OptionRow] = []

        hint = QLabel("Doğru şıkkı soldaki yuvarlak işaretle seçin.")
        hint.setObjectName("subtitle")
        self.rows_layout = QVBoxLayout()
        self.add_button = _button("+ Şık ekle", "secondary")
        self.add_button.clicked.connect(self._add_empty_option)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(hint)
        layout.addLayout(self.rows_layout)
        layout.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def set_options(self, options: list[OptionDraft]) -> None:
        for row in list(self.rows):
            self._remove_row(row)
        for option in options:
            self.add_option(option.text, option.is_correct)
        while len(self.rows) < MIN_OPTIONS:
            self.add_option()

    def add_option(self, text: str = "", is_correct: bool = False) -> None:
        if len(self.rows) >= MAX_OPTIONS:
            return
        row = _OptionRow(self.group)
        row.text_input.setText(text)
        row.radio.setChecked(is_correct)
        row.delete_requested.connect(self._remove_row)
        self.rows.append(row)
        self.rows_layout.addWidget(row)
        self._refresh()

    def _add_empty_option(self) -> None:
        self.add_option()
        self.rows[-1].text_input.setFocus()

    def _remove_row(self, row: _OptionRow) -> None:
        self.rows.remove(row)
        self.group.removeButton(row.radio)
        row.deleteLater()
        self._refresh()

    def _refresh(self) -> None:
        """Harfleri yeniden yazar, sınırlara göre ekle/sil butonlarını açıp kapatır."""
        for letter, row in zip(OPTION_LETTERS, self.rows):
            row.letter.setText(f"{letter})")
            row.delete_button.setEnabled(len(self.rows) > MIN_OPTIONS)
        self.add_button.setEnabled(len(self.rows) < MAX_OPTIONS)

    def options(self) -> list[OptionDraft]:
        return [OptionDraft(r.text_input.text(), r.radio.isChecked()) for r in self.rows]


# ---------------------------------------------------------------------------
# Klasik soru: kabul edilen cevaplar
# ---------------------------------------------------------------------------

class ClassicEditor(QWidget):
    """Kabul edilen cevap listesi. Çift tıklayarak bir cevap düzenlenebilir."""

    def __init__(self) -> None:
        super().__init__()
        hint = QLabel(
            "Öğrencinin cevabı bunlardan biriyle eşleşirse tam puan alır.\n"
            "Karşılaştırma büyük-küçük harfe ve fazla boşluklara duyarsızdır."
        )
        hint.setObjectName("subtitle")

        self.answer_input = QLineEdit()
        self.answer_input.setPlaceholderText("Kabul edilen cevap yazıp Enter'a basın")
        self.answer_input.returnPressed.connect(self._add_from_input)
        add_button = _button("Ekle", "secondary")
        add_button.clicked.connect(self._add_from_input)
        input_row = QHBoxLayout()
        input_row.addWidget(self.answer_input, stretch=1)
        input_row.addWidget(add_button)

        self.list_widget = QListWidget()
        self.list_widget.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.remove_button = _button("Seçileni sil", "secondary")
        self.remove_button.clicked.connect(self._remove_selected)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(hint)
        layout.addLayout(input_row)
        layout.addWidget(self.list_widget, stretch=1)
        layout.addWidget(self.remove_button, alignment=Qt.AlignmentFlag.AlignLeft)

    def set_answers(self, answers: list[str]) -> None:
        self.list_widget.clear()
        for answer in answers:
            self._add(answer)

    def _add(self, answer: str) -> None:
        item = QListWidgetItem(answer)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list_widget.addItem(item)

    def _add_from_input(self) -> None:
        answer = self.answer_input.text().strip()
        if answer and answer not in self.answers():
            self._add(answer)
        self.answer_input.clear()

    def _remove_selected(self) -> None:
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def answers(self) -> list[str]:
        """Listedekiler + kutuda yazılı kalmış (Ekle'ye basılmamış) cevap."""
        result = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        pending = self.answer_input.text().strip()
        if pending:
            result.append(pending)
        return result


# ---------------------------------------------------------------------------
# Ana pencere
# ---------------------------------------------------------------------------

class QuestionDialog(QDialog):
    """Yeni soru (detail=None) veya düzenleme.

    exec() Accepted dönerse self.saved_id kaydedilen sorunun id'sidir.
    Kullanıcı "Çoğalt ve düzenle"ye basarsa pencere kapanır ve self.wants_duplicate True olur.
    """

    def __init__(
        self, categories: list[CategoryRow], detail: QuestionDetail | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.detail = detail
        self.saved_id: int | None = None
        self.wants_duplicate = False
        self.setWindowTitle("Yeni soru" if detail is None else f"Soru düzenle (No {detail.id})")
        self.resize(720, 680)

        self.form_area = QWidget()
        form_layout = QVBoxLayout(self.form_area)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.addLayout(self._build_fields(categories))
        form_layout.addWidget(self._build_text_area(), stretch=2)

        self.mcq_editor = McqEditor()
        self.classic_editor = ClassicEditor()
        self.code_placeholder = QLabel("Kod soruları Final'de eklenecek.")
        self.code_placeholder.setObjectName("placeholder")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.mcq_editor)
        self.stack.addWidget(self.classic_editor)
        self.stack.addWidget(self.code_placeholder)
        form_layout.addWidget(self.stack, stretch=3)

        self.error_box = make_error_box()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        self.warning_label = QLabel(
            "Bu soru yapılmış bir sınavda kullanıldı; eski sonuçlar bozulmasın diye "
            "değiştirilemez. Değişiklik yapmak için soruyu çoğaltıp kopyasını düzenleyin."
        )
        self.warning_label.setObjectName("warning")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        layout.addWidget(self.warning_label)
        layout.addWidget(self.form_area, stretch=1)
        layout.addWidget(self.error_box)
        layout.addLayout(self._build_buttons())

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._fill(detail)

    # --- Kurulum ---

    def _build_fields(self, categories: list[CategoryRow]) -> QFormLayout:
        self.type_combo = QComboBox()
        self.type_combo.addItem("Test (çoktan seçmeli)", "mcq")
        self.type_combo.addItem("Klasik (kısa cevap)", "classic")
        self.type_combo.addItem("Kod (C programlama)", "code")
        code_item = self.type_combo.model().item(2)
        code_item.setEnabled(False)  # Final'de açılacak
        code_item.setToolTip("Final'de eklenecek")

        self.category_combo = QComboBox()
        self.category_combo.addItem("(Kategorisiz)", None)
        for category in categories:
            self.category_combo.addItem(category.name, category.id)

        self.points_spin = QDoubleSpinBox()
        self.points_spin.setRange(0.5, MAX_POINTS)
        self.points_spin.setSingleStep(1)
        self.points_spin.setDecimals(1)
        self.points_spin.setValue(10)

        form = QFormLayout()
        form.addRow("Tür:", self.type_combo)
        form.addRow("Kategori:", self.category_combo)
        form.addRow("Varsayılan puan:", self.points_spin)
        return form

    def _build_text_area(self) -> QWidget:
        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText("Soru metni (kod parçası içerebilir)")
        self.text_input.setTabChangesFocus(False)
        self.mono_check = QCheckBox("Eşit genişlikli yazı tipi (kod için)")
        self.mono_check.toggled.connect(self._set_monospace)

        header = QHBoxLayout()
        header.addWidget(QLabel("Soru metni:"))
        header.addStretch()
        header.addWidget(self.mono_check)

        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self.text_input)
        return box

    def _build_buttons(self) -> QHBoxLayout:
        self.duplicate_button = _button("Çoğalt ve düzenle", "secondary")
        self.duplicate_button.clicked.connect(self._request_duplicate)
        self.duplicate_button.hide()
        cancel_button = _button("Vazgeç", "secondary")
        cancel_button.clicked.connect(self.reject)
        self.save_button = _button("Kaydet")
        self.save_button.clicked.connect(self._save)

        buttons = QHBoxLayout()
        buttons.addWidget(self.duplicate_button)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.save_button)
        return buttons

    def _fill(self, detail: QuestionDetail | None) -> None:
        if detail is None:
            self.mcq_editor.set_options([OptionDraft("") for _ in range(DEFAULT_OPTION_COUNT)])
            self.classic_editor.set_answers([])
            self._on_type_changed()
            self.text_input.setFocus()
            return

        draft = detail.draft
        self.type_combo.setCurrentIndex(self.type_combo.findData(draft.type))
        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(draft.category_id)))
        self.points_spin.setValue(draft.default_points)
        self.text_input.setPlainText(draft.text)
        self.mono_check.setChecked(looks_like_code(draft.text))
        self.mcq_editor.set_options(draft.options or [OptionDraft("") for _ in range(DEFAULT_OPTION_COUNT)])
        self.classic_editor.set_answers(draft.accepted_answers)
        self._on_type_changed()
        self.text_input.setFocus()

        if detail.used_in_started_exam:
            self.warning_label.show()
            self.form_area.setEnabled(False)
            self.save_button.hide()
            self.duplicate_button.show()

    # --- Olaylar ---

    def _on_type_changed(self) -> None:
        index = {"mcq": 0, "classic": 1}.get(self.type_combo.currentData(), 2)
        self.stack.setCurrentIndex(index)
        show_errors(self.error_box, [])

    def _set_monospace(self, enabled: bool) -> None:
        set_monospace(self.text_input, enabled)

    def _request_duplicate(self) -> None:
        self.wants_duplicate = True
        self.reject()

    def build_draft(self) -> QuestionDraft:
        question_type = self.type_combo.currentData()
        return QuestionDraft(
            type=question_type,
            text=self.text_input.toPlainText(),
            category_id=self.category_combo.currentData(),
            default_points=self.points_spin.value(),
            options=self.mcq_editor.options() if question_type == "mcq" else [],
            accepted_answers=self.classic_editor.answers() if question_type == "classic" else [],
        )

    def _save(self) -> None:
        draft = self.build_draft()
        errors = question_bank.validate_draft(draft)
        if errors:
            show_errors(self.error_box, errors)
            return
        try:
            if self.detail is None:
                self.saved_id = question_bank.create_question(draft)
            else:
                question_bank.update_question(self.detail.id, draft)
                self.saved_id = self.detail.id
        except QuestionBankError as error:
            show_errors(self.error_box, error.message.splitlines())
            return
        self.accept()
