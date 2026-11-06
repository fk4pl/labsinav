"""Sınav ekranının parçaları. (Sahibi: C)

    TopBar        üst bar: sınav adı, öğrenci, geri sayım, bağlantı, kayıt durumu
    QuestionGrid  sol panel: soru numarası butonları
    QuestionPage  tek bir sorunun metni + cevap alanı
    *Editor       soru tipine göre cevap alanı (şıklar / metin / kod)

Bu parçalar sadece görüntüden sorumludur; ağ ve zamanlama işleri exam_view.py'dedir.
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from shared import theme
from shared.protocol import QuestionForStudent, SavedAnswer, UserInfo
from student_app.ui.question_text import question_to_html
from student_app.ui.style import WARNING, repolish

# protocol.SaveAnswerRequest sınırları: daha uzun cevap sunucuda reddedilir.
MAX_TEXT_ANSWER = 10_000
MAX_CODE = 100_000
GRID_COLUMNS = 4


def set_level(label: QLabel, text: str, level: str) -> None:
    """Etiketin metnini ve renk seviyesini (style.py'deki [level=...]) değiştirir."""
    label.setText(text)
    label.setProperty("level", level)
    repolish(label)


# ----------------------------------------------------------------------
# Üst bar
# ----------------------------------------------------------------------

class TopBar(QFrame):
    zoom_in_clicked = Signal()
    zoom_out_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        left = QVBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("examTitle")
        self.student_label = QLabel()
        self.student_label.setObjectName("subtitle")
        left.addWidget(self.title_label)
        left.addWidget(self.student_label)
        layout.addLayout(left, stretch=1)

        self.countdown_label = QLabel("--:--")
        self.countdown_label.setObjectName("countdown")
        self.countdown_label.setToolTip("Kalan süre")
        layout.addWidget(self.countdown_label)

        right = QVBoxLayout()
        self.connection_label = QLabel()
        self.connection_label.setObjectName("status")
        self.save_label = QLabel()
        self.save_label.setObjectName("status")
        right.addWidget(self.connection_label, alignment=Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.save_label, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(right, stretch=1)

        for text, tip, signal in (
            ("A−", "Yazıyı küçült (Ctrl -)", self.zoom_out_clicked),
            ("A+", "Yazıyı büyüt (Ctrl +)", self.zoom_in_clicked),
        ):
            button = QPushButton(text)
            button.setObjectName("secondary")
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(signal)
            layout.addWidget(button)

    def show_exam(self, title: str, user: UserInfo | None) -> None:
        self.title_label.setText(title)
        if user is None:
            self.student_label.setText("")
        else:
            self.student_label.setText(f"{user.full_name}  •  {user.username}")

    def show_remaining(self, seconds: float) -> None:
        seconds = max(0, int(seconds + 0.999))  # 0.4 sn kaldıysa 00:01 göster
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
        if seconds <= 60:
            level = "danger"
        elif seconds <= 300:
            level = "warning"
        else:
            level = "normal"
        if text != self.countdown_label.text() or level != self.countdown_label.property("level"):
            set_level(self.countdown_label, text, level)


# ----------------------------------------------------------------------
# Soru numaraları ızgarası
# ----------------------------------------------------------------------

# Izgaradaki buton durumları ve ipucu metinleri
STATUS_TIPS = {
    "answered_marked": "Cevaplandı, sonra bakacağım",
    "marked": "Sonra bakacağım (cevapsız)",
    "answered": "Cevaplandı",
    "empty": "Boş",
}


def question_status(answered: bool, marked: bool) -> str:
    if answered and marked:
        return "answered_marked"
    if marked:
        return "marked"
    return "answered" if answered else "empty"


class QuestionButton(QPushButton):
    """Soru numarası butonu. Cevaplanmış + işaretli soruda sağ üst köşeye turuncu bayrak çizer.

    Tıklanınca kendi sırasını (index) index_clicked sinyaliyle bildirir; böylece
    bağlantı için lambda gerekmez.
    """

    index_clicked = Signal(int)

    def __init__(self, text: str, index: int, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.index = index
        self.flagged = False
        self.clicked.connect(self._emit_index)

    def _emit_index(self) -> None:
        self.index_clicked.emit(self.index)

    def set_flagged(self, flagged: bool) -> None:
        self.flagged = flagged
        self.update()  # yeniden çizilsin

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)  # önce normal buton (yeşil kutu, numara)
        if not self.flagged:
            return
        size = max(8.0, self.width() * 0.36)
        right, top = self.width() - 2.0, 2.0  # 2 px: kenarlığın içinde kalsın
        triangle = QPolygonF([
            QPointF(right - size, top), QPointF(right, top), QPointF(right, top + size),
        ])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("white"), 1))  # yeşil üstünde ayrı görünsün diye ince beyaz çizgi
        painter.setBrush(QColor(WARNING))
        painter.drawPolygon(triangle)
        painter.end()


class QuestionGrid(QWidget):
    question_clicked = Signal(int)  # soru sırası (0'dan başlar)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: list[QuestionButton] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Sorular")
        title.setObjectName("questionHeader")
        layout.addWidget(title)
        self._grid = QGridLayout()
        self._grid.setSpacing(6)
        layout.addLayout(self._grid)
        legend = QLabel(
            f'<span style="color:{theme.SUCCESS}">■</span> cevaplandı<br>'
            f'<span style="color:{theme.SUCCESS}">■</span><span style="color:{WARNING}">◥</span>'
            ' cevaplandı, sonra bakacağım<br>'
            f'<span style="color:{WARNING}">■</span> sonra bakacağım (cevapsız)<br>'
            f'<span style="color:{theme.BORDER}">■</span> boş<br>'
            f'<span style="color:{theme.PRIMARY}">□</span> şu anki soru'
        )
        legend.setObjectName("legend")
        layout.addSpacing(8)
        layout.addWidget(legend)
        layout.addStretch()

    def build(self, count: int) -> None:
        for button in self._buttons:
            button.deleteLater()
        self._buttons = []
        for index in range(count):
            button = QuestionButton(str(index + 1), index)
            button.setObjectName("questionNumber")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.index_clicked.connect(self.question_clicked)  # sinyali sinyale bağlamak: aynen iletir
            self._grid.addWidget(button, index // GRID_COLUMNS, index % GRID_COLUMNS)
            self._buttons.append(button)

    def set_status(self, index: int, answered: bool, marked: bool, current: bool) -> None:
        button = self._buttons[index]
        status = question_status(answered, marked)
        button.setProperty("status", status)
        button.setProperty("current", "true" if current else "false")
        button.set_flagged(status == "answered_marked")
        button.setToolTip(f"Soru {index + 1}: {STATUS_TIPS[status]}")
        repolish(button)


# ----------------------------------------------------------------------
# Cevap alanları
# ----------------------------------------------------------------------

class AnswerEditor(QWidget):
    """Tüm cevap alanlarının ortak arayüzü."""

    changed = Signal()

    def value(self) -> SavedAnswer:
        raise NotImplementedError

    def set_value(self, answer: SavedAnswer | None) -> None:
        raise NotImplementedError

    def set_locked(self, locked: bool) -> None:
        self.setEnabled(not locked)


class McqEditor(AnswerEditor):
    """Çoktan seçmeli: radio butonlar + 'Seçimi kaldır'."""

    def __init__(self, question: QuestionForStudent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._group = QButtonGroup(self)
        options = sorted(question.options, key=lambda o: o.order_index)
        for index, option in enumerate(options):
            letter = chr(ord("A") + index) if index < 26 else str(index + 1)
            radio = QRadioButton(f"{letter})  {option.text.replace('`', '')}")
            if "`" in option.text or "\n" in option.text:
                radio.setObjectName("codeOption")  # şık kod içeriyorsa eşit genişlikli font
            self._group.addButton(radio, option.id)
            layout.addWidget(radio)
        self._group.idToggled.connect(self._on_toggled)

        clear = QPushButton("Seçimi kaldır")
        clear.setObjectName("secondary")
        clear.clicked.connect(self._clear)
        layout.addWidget(clear, alignment=Qt.AlignmentFlag.AlignLeft)

    def _on_toggled(self, _option_id: int, checked: bool) -> None:
        if checked:
            self.changed.emit()

    def _clear(self) -> None:
        if self._group.checkedId() == -1:
            return
        self._group.setExclusive(False)  # exclusive grupta hiçbiri seçilmemiş hale getirilemez
        self._group.checkedButton().setChecked(False)
        self._group.setExclusive(True)
        self.changed.emit()

    def value(self) -> SavedAnswer:
        option_id = self._group.checkedId()
        return SavedAnswer(selected_option_id=option_id if option_id != -1 else None)

    def set_value(self, answer: SavedAnswer | None) -> None:
        self.blockSignals(True)
        self._group.blockSignals(True)
        self._group.setExclusive(False)
        for button in self._group.buttons():
            button.setChecked(answer is not None and self._group.id(button) == answer.selected_option_id)
        self._group.setExclusive(True)
        self._group.blockSignals(False)
        self.blockSignals(False)


class _LimitedTextEdit(QPlainTextEdit):
    """Uzunluk sınırı olan metin alanı (QPlainTextEdit'te hazır maxLength yok)."""

    def __init__(self, max_length: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_length = max_length
        self.textChanged.connect(self._enforce_limit)

    def _enforce_limit(self) -> None:
        text = self.toPlainText()
        if len(text) > self._max_length:
            self.setPlainText(text[: self._max_length])
            self.moveCursor(self.textCursor().MoveOperation.End)


class _CodeTextEdit(_LimitedTextEdit):
    """Tab tuşu 4 boşluk ekler (odağı başka alana atlatmaz)."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText("    ")
            return
        super().keyPressEvent(event)


class TextEditor(AnswerEditor):
    """Klasik soru: kısa cevap metin alanı."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = _LimitedTextEdit(MAX_TEXT_ANSWER)
        self._edit.setPlaceholderText("Cevabını buraya yaz…")
        self._edit.setMinimumHeight(140)
        self._edit.textChanged.connect(self.changed)
        layout.addWidget(self._edit)

    def value(self) -> SavedAnswer:
        return SavedAnswer(text_answer=self._edit.toPlainText())

    def set_value(self, answer: SavedAnswer | None) -> None:
        text = answer.text_answer if answer and answer.text_answer else ""
        if text != self._edit.toPlainText():
            self._edit.blockSignals(True)
            self._edit.setPlainText(text)
            self._edit.blockSignals(False)


class CodeEditor(AnswerEditor):
    """Kod sorusu: eşit genişlikli editör, başlangıç koduyla dolu gelir."""

    def __init__(self, starter_code: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._starter = starter_code or ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = _CodeTextEdit(MAX_CODE)
        self._edit.setObjectName("codeEditor")
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._edit.setMinimumHeight(260)
        self._edit.setPlainText(self._starter)
        self._edit.textChanged.connect(self.changed)
        layout.addWidget(self._edit)

    def value(self) -> SavedAnswer:
        return SavedAnswer(code=self._edit.toPlainText())

    def set_value(self, answer: SavedAnswer | None) -> None:
        code = answer.code if answer and answer.code is not None else self._starter
        if code != self._edit.toPlainText():
            self._edit.blockSignals(True)
            self._edit.setPlainText(code)
            self._edit.blockSignals(False)


def make_editor(question: QuestionForStudent) -> AnswerEditor:
    if question.type == "mcq":
        return McqEditor(question)
    if question.type == "code":
        return CodeEditor(question.starter_code)
    return TextEditor()


# ----------------------------------------------------------------------
# Tek soru sayfası
# ----------------------------------------------------------------------

class QuestionPage(QScrollArea):
    """Soru başlığı + metni + cevap alanı. Uzun sorular için kaydırılabilir.

    Cevap değişince answer_changed(soru id) sinyali yayılır.
    """

    answer_changed = Signal(int)

    def __init__(self, question: QuestionForStudent, number: int, total: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.question = question
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        content = QFrame()
        content.setObjectName("card")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        points = f"{question.points:g}"
        self.header_label = QLabel(f"Soru {number} / {total}  •  {points} puan")
        self.header_label.setObjectName("questionHeader")
        layout.addWidget(self.header_label)

        text = QLabel(question_to_html(question.text))
        text.setObjectName("questionText")
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(text)

        self.editor = make_editor(question)
        self.editor.changed.connect(self._emit_answer_changed)
        layout.addWidget(self.editor)
        layout.addStretch()
        self.setWidget(content)

    def _emit_answer_changed(self) -> None:
        self.answer_changed.emit(self.question.id)

    def set_marked(self, marked: bool, number: int, total: int) -> None:
        points = f"{self.question.points:g}"
        flag = "  •  ⚑ Sonra bakacağım" if marked else ""
        self.header_label.setText(f"Soru {number} / {total}  •  {points} puan{flag}")
