"""Soru önizleme: sorunun öğrenci ekranında nasıl görüneceği. (Sahibi: B)

Önizleme, öğrenciye gönderilen modelin AYNISINDAN (QuestionForStudent) çizilir.
Bu modelde cevap anahtarı olmadığı için önizlemede doğru şık işaretli değildir.
"""

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.widgets import format_points, set_monospace
from shared.protocol import QuestionForStudent

OPTION_LETTERS = "ABCDEF"


class QuestionPreviewDialog(QDialog):
    def __init__(self, question: QuestionForStudent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Soru önizleme (öğrenci görünümü)")
        self.resize(640, 480)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(12)

        header = QLabel(f"Soru 1  •  {format_points(question.points)} puan")
        header.setObjectName("subtitle")
        card_layout.addWidget(header)

        # Soru metni salt okunur bir metin kutusunda: kod parçalarındaki girintiler korunur.
        self.text_view = QPlainTextEdit(question.text)
        self.text_view.setReadOnly(True)
        self.text_view.setFrameShape(QFrame.Shape.NoFrame)
        card_layout.addWidget(self.text_view, stretch=1)

        if question.type == "mcq":
            card_layout.addWidget(self._build_options(question))
        elif question.type == "classic":
            answer_box = QPlainTextEdit()
            answer_box.setPlaceholderText("Cevabınızı buraya yazın…")
            answer_box.setMaximumHeight(90)
            card_layout.addWidget(answer_box)

        self.mono_check = QCheckBox("Soru metnini eşit genişlikli yazı tipiyle göster")
        self.mono_check.toggled.connect(self._set_monospace)
        close_button = QPushButton("Kapat")
        close_button.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addWidget(self.mono_check)
        bottom.addStretch()
        bottom.addWidget(close_button)

        note = QLabel("Bu bir önizlemedir; burada seçilen cevaplar kaydedilmez.")
        note.setObjectName("subtitle")

        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(card, stretch=1)
        layout.addLayout(bottom)

        self.mono_check.setChecked(looks_like_code(question.text))

    def _build_options(self, question: QuestionForStudent) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        group = QButtonGroup(box)
        for letter, option in zip(OPTION_LETTERS, question.options):
            radio = QRadioButton(f"{letter})  {option.text}")
            group.addButton(radio)
            layout.addWidget(radio)
        return box

    def _set_monospace(self, enabled: bool) -> None:
        set_monospace(self.text_view, enabled)


def looks_like_code(text: str) -> bool:
    """Metinde girintili satır veya süslü parantez varsa kod parçası içeriyor sayılır."""
    return "{" in text or any(line.startswith(("    ", "\t")) for line in text.splitlines())
