"""Sınav ekranı: sorular, cevaplar, geri sayım. (Sahibi: C)

Bu ekran ağdan habersizdir. Sunucuya bir şey yollamak istediğinde sinyal yayar:
    save_requested(SaveAnswerRequest)   -> cevabı kaydet
    submit_requested(int)               -> sınavı bitir (exam_id)
    focus_lost(int)                     -> öğrenci pencereden çıktı (exam_id)
student_app/main.py bu sinyalleri gerçek sunucuya (veya --demo'da sahte sunucuya) bağlar.

Otomatik kayıt (debounce): her değişiklikte 2 sn'lik zamanlayıcı baştan başlar. Öğrenci
2 sn yazmayı bırakınca o ana kadar değişen tüm cevaplar tek seferde gönderilir.
Soru değiştirince ve "Sınavı Bitir"e basınca beklemeden gönderilir.
"""

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from shared import config
from shared.protocol import ExamStart, SaveAnswerRequest, SaveOk, UserInfo
from student_app.exam_state import ExamState
from student_app.net.client import ConnectionState
from student_app.net.server_clock import ServerClock
from student_app.ui.exam_widgets import QuestionGrid, QuestionPage, TopBar, set_level

COUNTDOWN_TICK_MS = 250
BANNER_MS = 8000
WARNING_THRESHOLDS_SEC = (300, 60)  # 5. ve 1. dakika uyarıları


class ExamView(QWidget):
    save_requested = Signal(object)  # SaveAnswerRequest
    submit_requested = Signal(int)
    focus_lost = Signal(int)
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()

    def __init__(self, clock: ServerClock, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.clock = clock
        self.state = ExamState()
        self._pages: list[QuestionPage] = []
        self._current = 0
        self._ends_at: datetime | None = None
        self._online = False
        self._locked = False         # süre doldu / gönderiliyor: cevaplar değiştirilemez
        self._submitting = False
        self._warned: set[int] = set()

        self._build_ui()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(config.SAVE_DEBOUNCE_SEC * 1000)
        self._save_timer.timeout.connect(self.flush_saves)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(COUNTDOWN_TICK_MS)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self.banner.hide)

        QApplication.instance().applicationStateChanged.connect(self._on_app_state_changed)

    # ------------------------------------------------------------------
    # Arayüzün kurulması
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.top_bar = TopBar()
        self.top_bar.zoom_in_clicked.connect(self.zoom_in_requested)
        self.top_bar.zoom_out_clicked.connect(self.zoom_out_requested)

        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()

        self.grid = QuestionGrid()
        self.grid.setFixedWidth(200)
        self.grid.question_clicked.connect(self.go_to)

        self.question_stack = QStackedWidget()

        self.prev_button = QPushButton("◀ Önceki")
        self.prev_button.setObjectName("secondary")
        self.prev_button.clicked.connect(lambda: self.go_to(self._current - 1))
        self.mark_button = QPushButton("⚑ İşaretle")
        self.mark_button.setObjectName("secondary")
        self.mark_button.setToolTip("Bu soruya sonra bakmak için işaretle")
        self.mark_button.clicked.connect(self._toggle_mark)
        self.next_button = QPushButton("Sonraki ▶")
        self.next_button.setObjectName("secondary")
        self.next_button.clicked.connect(lambda: self.go_to(self._current + 1))
        self.finish_button = QPushButton("Sınavı Bitir")
        self.finish_button.setObjectName("danger")
        self.finish_button.clicked.connect(self._on_finish_clicked)

        nav = QHBoxLayout()
        nav.addWidget(self.prev_button)
        nav.addWidget(self.mark_button)
        nav.addWidget(self.next_button)
        nav.addStretch()
        nav.addWidget(self.finish_button)

        center = QVBoxLayout()
        center.setContentsMargins(16, 16, 16, 16)
        center.addWidget(self.question_stack, stretch=1)
        center.addLayout(nav)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        side = QFrame()
        side.setObjectName("card")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self.grid)
        body.addWidget(side)
        body.addLayout(center, stretch=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.top_bar)
        layout.addWidget(self.banner)
        layout.addLayout(body, stretch=1)

    # ------------------------------------------------------------------
    # Dışarıdan çağrılanlar (main.py)
    # ------------------------------------------------------------------

    @property
    def exam_id(self) -> int | None:
        return self.state.exam_id

    @property
    def is_active(self) -> bool:
        """Sınav sürüyor mu (yüklü ve bitmemiş)?"""
        return self.state.exam is not None and self._countdown_timer.isActive()

    def load_exam(self, start: ExamStart, user: UserInfo | None) -> None:
        """exam_start geldi. Aynı sınav tekrar geldiyse ekran yeniden kurulmaz, sadece cevaplar yenilenir."""
        same_exam = self.state.load(start)
        self.top_bar.show_exam(start.exam.title, user)
        if not same_exam:
            self._build_pages()
            self._current = 0
        self._show_saved_answers()
        self._locked = False
        self._submitting = False
        self.finish_button.setEnabled(True)
        self._set_locked_editors(False)
        self._set_end_time(start.ends_at)
        self._countdown_timer.start()
        self.go_to(min(self._current, len(self._pages) - 1))
        self.flush_saves()  # yerelde kaydedilmemiş cevap varsa hemen gönder

    def update_end_time(self, ends_at: datetime) -> None:
        """Eğitmen süre ekledi (exam_update)."""
        self._set_end_time(ends_at)
        if self._locked and self.clock.seconds_until(ends_at) > 0 and not self._submitting:
            self._locked = False
            self._set_locked_editors(False)
        self.show_banner("Eğitmen sınav süresini güncelledi.", "info")

    def set_connection_state(self, state: str) -> None:
        self._online = state == ConnectionState.CONNECTED
        if state == ConnectionState.CONNECTED:
            set_level(self.top_bar.connection_label, "● Bağlı", "ok")
        elif state == ConnectionState.RECONNECTING:
            self.state.forget_sent()  # onayı gelmeyen kayıtlar tekrar gönderilecek
            set_level(self.top_bar.connection_label, "● Bağlantı koptu, yeniden bağlanıyor…", "warning")
        else:
            self.state.forget_sent()
            set_level(self.top_bar.connection_label, "● Bağlantı yok", "danger")
        if self._online:
            self.flush_saves()
        self._refresh_save_status()

    def on_save_ok(self, reply: SaveOk) -> None:
        self.state.mark_saved(reply.question_id)
        self._refresh_save_status()

    def on_request_failed(self, request_type: str, message: str) -> None:
        """Sunucu bir isteği reddetti (sınavı bitiren hatalar dışında)."""
        self.state.forget_sent()  # bir sonraki kayıtta tekrar denenecek
        if request_type == "submit":
            self._submitting = False
            self._locked = False
            self._set_locked_editors(False)
            self.finish_button.setEnabled(True)
        self.show_banner(f"İşlem tamamlanamadı: {message}", "danger")
        self._refresh_save_status()

    def stop(self) -> None:
        """Sınav bitti (gönderildi / süre doldu): zamanlayıcıları durdur."""
        self._save_timer.stop()
        self._countdown_timer.stop()
        self._locked = True
        self._set_locked_editors(True)

    def reset(self) -> None:
        """Başka öğrenci giriş yaptı: önceki öğrencinin cevapları asla taşınmasın."""
        self.stop()
        self.state = ExamState()
        self._build_pages()

    def show_banner(self, text: str, level: str = "info") -> None:
        set_level(self.banner, text, level)
        self.banner.show()
        self._banner_timer.start(BANNER_MS)

    # ------------------------------------------------------------------
    # Sorular ve gezinme
    # ------------------------------------------------------------------

    def _build_pages(self) -> None:
        for page in self._pages:
            self.question_stack.removeWidget(page)
            page.deleteLater()
        questions = self.state.questions
        self._pages = []
        for number, question in enumerate(questions, start=1):
            page = QuestionPage(question, number, len(questions))
            page.editor.changed.connect(lambda qid=question.id, p=page: self._on_answer_changed(qid, p))
            self.question_stack.addWidget(page)
            self._pages.append(page)
        self.grid.build(len(questions))

    def _show_saved_answers(self) -> None:
        """ExamState'teki cevapları ekrandaki alanlara yazar (yeniden bağlanınca da)."""
        for page in self._pages:
            page.editor.set_value(self.state.answer_for(page.question.id))
        self._refresh_grid()
        self._refresh_save_status()

    def go_to(self, index: int) -> None:
        if not self._pages or not 0 <= index < len(self._pages):
            return
        if index != self._current:
            self.flush_saves()
        self._current = index
        self.question_stack.setCurrentIndex(index)
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self._pages) - 1)
        self._refresh_mark_button()
        self._refresh_grid()

    def _toggle_mark(self) -> None:
        if not self._pages:
            return
        self.state.toggle_mark(self._pages[self._current].question.id)
        self._refresh_mark_button()
        self._refresh_grid()

    def _refresh_mark_button(self) -> None:
        page = self._pages[self._current]
        marked = page.question.id in self.state.marked
        self.mark_button.setText("⚑ İşareti kaldır" if marked else "⚑ İşaretle")
        page.set_marked(marked, self._current + 1, len(self._pages))

    def _refresh_grid(self) -> None:
        for index, page in enumerate(self._pages):
            qid = page.question.id
            self.grid.set_status(
                index, self.state.is_answered(qid), qid in self.state.marked, index == self._current
            )

    # ------------------------------------------------------------------
    # Cevap kaydetme
    # ------------------------------------------------------------------

    def _on_answer_changed(self, question_id: int, page: QuestionPage) -> None:
        if self._locked:
            return
        self.state.set_answer(question_id, page.editor.value())
        self._refresh_grid()
        self._refresh_save_status()
        self._save_timer.start()  # her değişiklikte 2 sn baştan başlar (debounce)

    def flush_saves(self) -> None:
        """Kaydedilmemiş cevapları hemen gönderir (bağlıysak)."""
        self._save_timer.stop()
        if not self._online or self.state.exam is None:
            return
        for qid in self.state.take_unsent():
            answer = self.state.answer_for(qid)
            assert answer is not None
            self.save_requested.emit(SaveAnswerRequest(
                exam_id=self.state.exam.id, question_id=qid,
                selected_option_id=answer.selected_option_id,
                text_answer=answer.text_answer, code=answer.code,
            ))
        self._refresh_save_status()

    def _refresh_save_status(self) -> None:
        label = self.top_bar.save_label
        if self.state.dirty and not self._online:
            set_level(label, "Kaydedilemedi — cevapların bu bilgisayarda duruyor", "warning")
        elif self.state.dirty:
            set_level(label, "Kaydediliyor…", "busy")
        elif self.state.answers:
            set_level(label, "Kaydedildi ✓", "ok")
        else:
            set_level(label, "", "busy")

    def _set_locked_editors(self, locked: bool) -> None:
        for page in self._pages:
            page.editor.set_locked(locked)

    # ------------------------------------------------------------------
    # Süre
    # ------------------------------------------------------------------

    def _set_end_time(self, ends_at: datetime) -> None:
        self._ends_at = ends_at
        remaining = self.clock.seconds_until(ends_at)
        # Zaten geçilmiş eşikler için uyarı verme; süre uzatılınca uyarılar yeniden kurulur.
        self._warned = {t for t in WARNING_THRESHOLDS_SEC if remaining <= t}
        self._on_countdown_tick()

    def _on_countdown_tick(self) -> None:
        if self._ends_at is None:
            return
        remaining = self.clock.seconds_until(self._ends_at)
        self.top_bar.show_remaining(remaining)
        for threshold in WARNING_THRESHOLDS_SEC:
            if remaining <= threshold and threshold not in self._warned:
                self._warned.add(threshold)
                self._warn(threshold)
        if remaining <= 0 and not self._locked:
            self._on_time_up()

    def _warn(self, threshold: int) -> None:
        minutes = threshold // 60
        level = "danger" if threshold <= 60 else "warning"
        self.show_banner(f"Dikkat: sınavın bitmesine {minutes} dakika kaldı!", level)
        QApplication.beep()

    def _on_time_up(self) -> None:
        """Süre bizim saatimize göre doldu. Sunucu otomatik gönderip exam_end yollayacak."""
        self.flush_saves()
        self._locked = True
        self._set_locked_editors(True)
        self.finish_button.setEnabled(False)
        self.show_banner("Süre doldu. Cevapların gönderiliyor…", "danger")

    # ------------------------------------------------------------------
    # Sınavı bitirme
    # ------------------------------------------------------------------

    def _on_finish_clicked(self) -> None:
        if self.state.exam is None or self._submitting:
            return
        if not self._online:
            QMessageBox.warning(
                self, "Bağlantı yok",
                "Sunucuya bağlı değilsin. Bağlantı geri gelince tekrar dene.\n"
                "Cevapların bu bilgisayarda duruyor.",
            )
            return
        if not self._confirm_finish():
            return
        self.flush_saves()  # önce bekleyen cevaplar; WebSocket mesaj sırasını korur
        self._submitting = True
        self._locked = True
        self._set_locked_editors(True)
        self.finish_button.setEnabled(False)
        self.show_banner("Sınavın gönderiliyor…", "info")
        self.submit_requested.emit(self.state.exam.id)

    def _confirm_finish(self) -> bool:
        lines = ["Sınavı bitirmek istediğine emin misin? Gönderdikten sonra değişiklik yapamazsın."]
        unanswered = self.state.unanswered_numbers()
        marked = self.state.marked_numbers()
        if unanswered:
            lines.append(f"\nCevaplanmamış sorular ({len(unanswered)}): {_join(unanswered)}")
        if marked:
            lines.append(f"\nSonra bakacağım diye işaretlediğin sorular: {_join(marked)}")
        box = QMessageBox(QMessageBox.Icon.Question, "Sınavı bitir", "\n".join(lines), parent=self)
        send = box.addButton("Gönder", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Vazgeç", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)  # yanlışlıkla Enter'a basınca gönderilmesin
        box.exec()
        return box.clickedButton() is send

    # ------------------------------------------------------------------
    # Pencereden çıkma
    # ------------------------------------------------------------------

    def _on_app_state_changed(self, state: Qt.ApplicationState) -> None:
        if state != Qt.ApplicationState.ApplicationActive and self.is_active and self.isVisible():
            assert self.state.exam is not None
            self.focus_lost.emit(self.state.exam.id)


def _join(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers)
