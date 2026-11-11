"""Öğrenci sonuç detayı penceresi. (Sahibi: D)

Her soru bir kart: soru metni, öğrencinin cevabı, doğru cevap, aldığı puan.
Klasik sorularda eğitmen puanı elle değiştirebilir ("Kaydet") veya elle verilen puanı
geri alıp otomatik puana dönebilir. Puan değişince pencere verileri yeniden okur.
"""

from datetime import datetime

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from instructor_app.ui.widgets import format_points, make_error_box, set_monospace, show_errors
from server.services import grading, results
from server.services.grading import GradingError
from server.services.question_bank import TYPE_LABELS
from server.services.results import AnswerDetail, ResultsError, StudentDetail


def format_local_time(moment: datetime | None) -> str:
    """UTC zamanı yerel saate çevirip '05.11.2026 13:05' biçiminde yazar."""
    if moment is None:
        return "—"
    return moment.astimezone().strftime("%d.%m.%Y %H:%M")


def plain_label(text: str) -> QLabel:
    """Öğrencinin yazdığı metni HTML olarak YORUMLAMAYAN etiket (ör. '<b>' aynen görünür)."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class AnswerCard(QFrame):
    """Tek bir sorunun sonucu. Puan değişince points_changed yayınlanır."""

    points_changed = Signal()

    def __init__(self, detail: AnswerDetail, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.detail = detail
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        header = QHBoxLayout()
        title = QLabel(
            f"Soru {detail.order} · {TYPE_LABELS.get(detail.question_type, detail.question_type)}"
            f" · {format_points(detail.max_points)} puan"
        )
        title.setStyleSheet("font-weight: 600;")
        self.status_label = QLabel()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.status_label)
        layout.addLayout(header)

        layout.addWidget(plain_label(detail.question_text))
        layout.addWidget(self._caption("Öğrencinin cevabı:"))
        layout.addWidget(self._given_widget(detail))
        layout.addWidget(self._caption("Doğru cevap:"))
        layout.addWidget(plain_label(detail.expected or "—"))

        if detail.can_edit:
            layout.addLayout(self._build_edit_row(detail))
            self.error_box = make_error_box()
            layout.addWidget(self.error_box)
        self.set_detail(detail)

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("subtitle")
        return label

    @staticmethod
    def _given_widget(detail: AnswerDetail) -> QWidget:
        if detail.is_blank:
            label = QLabel("(boş bırakıldı)")
            label.setObjectName("subtitle")
            return label
        if detail.question_type == "code":
            box = QPlainTextEdit(detail.given)
            box.setReadOnly(True)
            box.setMaximumHeight(220)
            set_monospace(box, True)
            return box
        return plain_label(detail.given)

    def _build_edit_row(self, detail: AnswerDetail) -> QHBoxLayout:
        row = QHBoxLayout()
        self.points_spin = QDoubleSpinBox()
        self.points_spin.setRange(0, detail.max_points)
        self.points_spin.setDecimals(2)
        self.points_spin.setSingleStep(0.5)
        self.points_spin.setLocale(QLocale(QLocale.Language.Turkish))  # 2,5 (virgüllü)
        save_button = QPushButton("Puanı kaydet")
        save_button.clicked.connect(self.save_points)
        self.reset_button = QPushButton("Otomatik puana dön")
        self.reset_button.setObjectName("link")
        self.reset_button.clicked.connect(self.reset_points)
        row.addWidget(QLabel("Elle puan:"))
        row.addWidget(self.points_spin)
        row.addWidget(save_button)
        row.addWidget(self.reset_button)
        row.addStretch()
        return row

    def set_detail(self, detail: AnswerDetail) -> None:
        """Puan/durum bilgilerini günceller (soru ve cevap metni değişmez)."""
        self.detail = detail
        self.status_label.setText(self._status_text(detail))
        self.status_label.setObjectName(self._status_style(detail))
        self.status_label.style().polish(self.status_label)  # objectName değişti, stili yenile
        if detail.can_edit:
            self.points_spin.setValue(detail.points or 0)
            self.reset_button.setVisible(detail.is_manual)

    @staticmethod
    def _status_text(detail: AnswerDetail) -> str:
        max_points = format_points(detail.max_points)
        if detail.is_blank and not detail.is_manual:
            return f"Boş — 0 / {max_points}"
        if detail.points is None:
            return "Puanlanmadı"
        score = f"{format_points(detail.points)} / {max_points}"
        if detail.is_correct:
            text = f"✓ Doğru — {score}"
        elif detail.points > 0:
            text = f"Kısmi puan — {score}"
        else:
            text = f"✗ Yanlış — {score}"
        return text + ("  (elle)" if detail.is_manual else "")

    @staticmethod
    def _status_style(detail: AnswerDetail) -> str:
        if detail.is_correct:
            return "success"
        if detail.points is None or detail.is_blank or detail.points > 0:
            return "subtitle"
        return "error"

    def save_points(self) -> None:
        assert self.detail.answer_id is not None
        try:
            grading.set_manual_points(self.detail.answer_id, self.points_spin.value())
        except GradingError as error:
            show_errors(self.error_box, [error.message])
            return
        show_errors(self.error_box, [])
        self.points_changed.emit()

    def reset_points(self) -> None:
        assert self.detail.answer_id is not None
        try:
            grading.clear_manual_points(self.detail.answer_id)
        except GradingError as error:
            show_errors(self.error_box, [error.message])
            return
        show_errors(self.error_box, [])
        self.points_changed.emit()


class StudentResultDialog(QDialog):
    """Bir öğrencinin sınav kâğıdı. changed: pencerede puan değiştirildi mi?"""

    def __init__(self, submission_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.submission_id = submission_id
        self.changed = False
        self.resize(780, 680)
        detail = results.student_detail(submission_id)  # ResultsError'u çağıran yakalar
        self.setWindowTitle(f"{detail.full_name} — {detail.exam_title}")

        layout = QVBoxLayout(self)
        self.title_label = QLabel(f"{detail.full_name}  ({detail.student_no})")
        self.title_label.setObjectName("title")
        self.info_label = QLabel()
        self.info_label.setObjectName("subtitle")
        layout.addWidget(self.title_label)
        layout.addWidget(self.info_label)

        self.cards = [AnswerCard(answer) for answer in detail.answers]
        layout.addWidget(self._build_card_list())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Kapat")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.show_info(detail)

    def _build_card_list(self) -> QScrollArea:
        container = QWidget()
        column = QVBoxLayout(container)
        for card in self.cards:
            card.points_changed.connect(self.on_points_changed)
            column.addWidget(card)
        column.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(container)
        return scroll

    def show_info(self, detail: StudentDetail) -> None:
        score = "Puanlanıyor…" if detail.score is None else format_points(detail.score)
        parts = [f"Puan: {score} / {format_points(detail.max_score)}"]
        if detail.status == "submitted":
            auto = " (süre dolunca otomatik)" if detail.auto_submitted else ""
            parts.append(f"Gönderim: {format_local_time(detail.submitted_at)}{auto}")
        else:
            parts.append("Öğrenci sınavı henüz göndermedi; puanlar gönderimden sonra verilir.")
        self.info_label.setText("   •   ".join(parts))

    def on_points_changed(self) -> None:
        """Bir kartta puan değişti: toplamı ve kartları veri tabanından yeniden oku."""
        self.changed = True
        try:
            detail = results.student_detail(self.submission_id)
        except ResultsError as error:
            self.info_label.setText(error.message)
            return
        self.show_info(detail)
        for card, answer in zip(self.cards, detail.answers):
            card.set_detail(answer)
