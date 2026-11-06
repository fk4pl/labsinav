"""Canlı Panel sekmesi: devam eden sınavı anlık izleme. (Sahibi: B)

Nasıl çalışır?
1. Sınav seçilince veri tabanından tam görüntü çekilir (exam_admin.get_live_snapshot) ve
   şu an kimin bağlı olduğu sunucudan öğrenilir (server.connected_students()).
2. Sonrasında veri tabanına tekrar sorulmaz: sunucudaki olaylar ServerBridge sinyalleriyle
   gelir (bağlandı, koptu, cevap kaydetti, gönderdi, pencereden çıktı, sınav bitti) ve
   sadece ilgili öğrencinin satırı güncellenir. Sinyaller Qt sayesinde UI thread'inde çalışır.
   TOPLU GÜNCELLEME: 40 öğrenci aynı anda yazarken saniyede yüzlerce sinyal gelebilir.
   Sinyal geldiğinde sadece bellekteki durum değişir ve öğrenci "kirli" işaretlenir;
   tablo en fazla UPDATE_INTERVAL_MS'de bir, kirli satırlar için toplu yenilenir.
3. Geri sayım her saniye ends_at - şimdi ile hesaplanır. Eğitmen uygulaması sunucunun
   kendisi olduğu için saat farkı yoktur.

Durum kuralı (öğrenci başına):
    gönderdi                         → Gönderdi
    bağlı ve sınav devam ediyor      → Sınavda
    bağlı                            → Bağlı
    değil                            → Çevrimdışı
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instructor_app.server_bridge import ServerBridge
from instructor_app.ui.widgets import format_local, make_button
from server.db.models import utcnow
from server.net.ws_server import ConnectedStudent, WsServer
from server.services import exam_admin
from server.services.exam_admin import ExamAdminError, LiveSnapshot, LiveStudentRow
from server.services.exam_session import ExamSessionError
from shared.theme import DANGER, MUTED, PRIMARY, SUCCESS, TEXT

logger = logging.getLogger(__name__)

WARNING_COLOR = "#d97706"   # turuncu
LOW_TIME_SECONDS = 5 * 60   # son 5 dakikada geri sayım kırmızı olur
UPDATE_INTERVAL_MS = 250    # tablo en fazla bu aralıkla yenilenir (toplu güncelleme)

OFFLINE, CONNECTED, IN_EXAM, SUBMITTED = "offline", "connected", "in_exam", "submitted"
STATUS_TEXT = {OFFLINE: "Çevrimdışı", CONNECTED: "Bağlı", IN_EXAM: "Sınavda", SUBMITTED: "Gönderdi"}
STATUS_COLOR = {OFFLINE: MUTED, CONNECTED: PRIMARY, IN_EXAM: WARNING_COLOR, SUBMITTED: SUCCESS}

COLUMNS = ["No", "Ad Soyad", "Durum", "Cevaplanan", "Son etkinlik", "Pencereden çıkma", "IP"]
COL_NO, COL_NAME, COL_STATUS, COL_ANSWERED, COL_ACTIVITY, COL_FOCUS, COL_IP = range(len(COLUMNS))

FINISH_REASONS = {"time_up": "süre doldu", "instructor_stopped": "eğitmen bitirdi"}


@dataclass
class StudentState:
    """Tablodaki bir öğrencinin o anki durumu (sinyaller geldikçe değişir)."""

    username: str
    full_name: str
    submitted: bool
    answered_count: int
    last_activity: datetime | None
    focus_lost_count: int
    ip: str | None
    connected: bool = False


def compute_status(state: StudentState, exam_running: bool) -> str:
    if state.submitted:
        return SUBMITTED
    if state.connected:
        return IN_EXAM if exam_running else CONNECTED
    return OFFLINE


class LivePanelPage(QWidget):
    def __init__(self, server: WsServer, bridge: ServerBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.server = server
        self.snapshot: LiveSnapshot | None = None
        self.ends_at: datetime | None = None
        self.states: dict[str, StudentState] = {}   # username → durum
        self.rows: dict[str, int] = {}               # username → tablo satırı
        self.badges: dict[str, QLabel] = {}          # username → durum rozeti
        self.badge_status: dict[str, str] = {}       # username → rozette şu an yazan durum
        self.dirty: set[str] = set()                 # tabloda henüz yenilenmemiş öğrenciler

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(self._build_header())
        layout.addLayout(self._build_counters())
        layout.addWidget(self._build_table(), stretch=1)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.setInterval(UPDATE_INTERVAL_MS)
        self.flush_timer.timeout.connect(self.flush_pending)

        bridge.student_connected.connect(self.on_student_connected)
        bridge.student_disconnected.connect(self.on_student_disconnected)
        bridge.answer_saved.connect(self.on_answer_saved)
        bridge.submitted.connect(self.on_submitted)
        bridge.focus_lost.connect(self.on_focus_lost)
        bridge.exam_finished.connect(self.on_exam_finished)

        self.refresh_exam_list()

    # --- Kurulum ---

    def _build_header(self) -> QHBoxLayout:
        self.exam_combo = QComboBox()
        self.exam_combo.setMinimumWidth(260)
        self.exam_combo.currentIndexChanged.connect(self._on_exam_selected)

        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        self.info_label = QLabel()
        self.info_label.setObjectName("subtitle")
        self.countdown_label = QLabel("--:--")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.extend5_button = make_button("+5 dk", "secondary")
        self.extend10_button = make_button("+10 dk", "secondary")
        self.stop_button = make_button("Sınavı Bitir", "danger")
        self.extend5_button.clicked.connect(self._extend_5)
        self.extend10_button.clicked.connect(self._extend_10)
        self.stop_button.clicked.connect(self._stop)

        titles = QVBoxLayout()
        selector = QHBoxLayout()
        selector.addWidget(QLabel("Sınav:"))
        selector.addWidget(self.exam_combo)
        selector.addStretch()
        titles.addLayout(selector)
        titles.addWidget(self.title_label)
        titles.addWidget(self.info_label)

        buttons = QHBoxLayout()
        buttons.addWidget(self.extend5_button)
        buttons.addWidget(self.extend10_button)
        buttons.addWidget(self.stop_button)
        right = QVBoxLayout()
        right.addWidget(self.countdown_label)
        right.addLayout(buttons)

        row = QHBoxLayout()
        row.addLayout(titles, stretch=1)
        row.addLayout(right)
        return row

    def _build_counters(self) -> QHBoxLayout:
        self.counter_labels: dict[str, QLabel] = {}
        row = QHBoxLayout()
        for status in (CONNECTED, IN_EXAM, SUBMITTED, OFFLINE):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            number = QLabel("0")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {STATUS_COLOR[status]};")
            caption = QLabel("Bağlı değil" if status == OFFLINE else STATUS_TEXT[status])
            caption.setObjectName("subtitle")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(number)
            card_layout.addWidget(caption)
            self.counter_labels[status] = number
            row.addWidget(card)
        return row

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self._set_column_modes()
        return self.table

    def _set_column_modes(self) -> None:
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)

    # --- Sınav seçimi ---

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh_exam_list()

    def refresh_exam_list(self) -> None:
        """Seçicide devam eden sınavlar + (bittiyse bile) şu an gösterilen sınav bulunur."""
        current_id = self.snapshot.exam_id if self.snapshot else None
        exams = exam_admin.list_running_exams()
        self.exam_combo.blockSignals(True)
        self.exam_combo.clear()
        for exam in exams:
            self.exam_combo.addItem(f"{exam.title} — {exam.class_name}", exam.id)
        if current_id is not None and self.exam_combo.findData(current_id) < 0:
            self.exam_combo.addItem(f"{self.snapshot.title} (bitti)", current_id)
        index = self.exam_combo.findData(current_id) if current_id is not None else 0
        self.exam_combo.setCurrentIndex(max(0, index))
        self.exam_combo.blockSignals(False)
        selected = self.exam_combo.currentData()
        if selected != current_id or self.snapshot is None:
            self.load(selected)

    def show_exam(self, exam_id: int) -> None:
        """Sınavlar sekmesinden 'Başlat' sonrası çağrılır."""
        self.load(exam_id)
        self.refresh_exam_list()

    def _on_exam_selected(self, _index: int) -> None:
        self.load(self.exam_combo.currentData())

    def load(self, exam_id: int | None) -> None:
        """Sınavın tam görüntüsünü veri tabanından ve sunucudan çeker; tabloyu baştan kurar."""
        self.snapshot = None
        if exam_id is not None:
            try:
                self.snapshot = exam_admin.get_live_snapshot(exam_id)
            except ExamAdminError as error:
                QMessageBox.warning(self, "Sınav açılamadı", error.message)
        self.ends_at = self.snapshot.ends_at if self.snapshot else None
        self._build_states()
        self._fill_table()
        self._update_header()
        self._tick()

    def _build_states(self) -> None:
        self.states = {}
        if self.snapshot is None:
            return
        connected = {s.username: s for s in self.server.connected_students()}
        for row in self.snapshot.students:
            self.states[row.username] = self._state_from_row(row, connected.get(row.username))

    @staticmethod
    def _state_from_row(row: LiveStudentRow, online: ConnectedStudent | None) -> StudentState:
        return StudentState(
            username=row.username,
            full_name=row.full_name,
            submitted=row.submission_status == "submitted",
            answered_count=row.answered_count,
            last_activity=row.last_activity,
            focus_lost_count=row.focus_lost_count,
            ip=online.ip if online else row.ip,
            connected=online is not None,
        )

    # --- Tablo ---

    def _fill_table(self) -> None:
        self.rows, self.badges, self.badge_status = {}, {}, {}
        self.dirty.clear()  # tablo baştan kuruluyor; bekleyen güncellemeye gerek yok
        # Satır satır eklemek her seferinde sütun genişliklerini yeniden hesaplatır (40 öğrencide
        # ~100 ms donma). Satır sayısını bir kerede verip çizimi iş bitene kadar kapatıyoruz.
        self.table.setUpdatesEnabled(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.states))
        for index, username in enumerate(self.states):
            for column in range(len(COLUMNS)):
                self.table.setItem(index, column, QTableWidgetItem())
            badge = QLabel()
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(index, COL_STATUS, badge)
            self.rows[username], self.badges[username] = index, badge
            self._update_row(username)
        self._set_column_modes()
        self.table.setUpdatesEnabled(True)
        self._update_counters()

    def _update_row(self, username: str) -> None:
        state = self.states[username]
        index = self.rows[username]
        total = self.snapshot.question_count if self.snapshot else 0
        values = {
            COL_NO: state.username,
            COL_NAME: state.full_name,
            COL_ANSWERED: f"{state.answered_count} / {total}",
            COL_ACTIVITY: format_local(state.last_activity, "%H:%M:%S"),
            COL_FOCUS: str(state.focus_lost_count),
            COL_IP: state.ip or "—",
        }
        for column, text in values.items():
            self.table.item(index, column).setText(text)
        focus_item = self.table.item(index, COL_FOCUS)
        focus_item.setForeground(QBrush(QColor(DANGER if state.focus_lost_count else TEXT)))

        status = compute_status(state, self._exam_running())
        if self.badge_status.get(username) == status:
            return  # setStyleSheet pahalıdır; durum değişmediyse dokunma
        self.badge_status[username] = status
        badge = self.badges[username]
        badge.setText(STATUS_TEXT[status])
        badge.setStyleSheet(
            f"background: {STATUS_COLOR[status]}; color: white; border-radius: 9px;"
            "padding: 2px 10px; margin: 3px 6px; font-weight: 600; font-size: 12px;"
        )

    def _update_counters(self) -> None:
        running = self._exam_running()
        counts = {status: 0 for status in STATUS_TEXT}
        for state in self.states.values():
            counts[compute_status(state, running)] += 1
        for status, label in self.counter_labels.items():
            label.setText(str(counts[status]))

    # --- Üst bilgi ve geri sayım ---

    def _exam_running(self) -> bool:
        return self.snapshot is not None and self.snapshot.status == "running"

    def _update_header(self) -> None:
        running = self._exam_running()
        for button in (self.extend5_button, self.extend10_button, self.stop_button):
            button.setEnabled(running)
        if self.snapshot is None:
            self.title_label.setText("Devam eden sınav yok")
            self.info_label.setText("Sınavlar sekmesinden bir sınav başlatın.")
            return
        self.title_label.setText(self.snapshot.title)
        info = f"Sınıf: {self.snapshot.class_name} · {self.snapshot.question_count} soru"
        if self.ends_at is not None:
            info += f" · Bitiş: {format_local(self.ends_at, '%H:%M:%S')}"
        self.info_label.setText(info)

    def _tick(self) -> None:
        if not self._exam_running() or self.ends_at is None:
            text = "Bitti" if self.snapshot is not None else "--:--"
            self._set_countdown(text, MUTED)
            return
        remaining = max(0, int((self.ends_at - utcnow()).total_seconds()))
        hours, rest = divmod(remaining, 3600)
        minutes, seconds = divmod(rest, 60)
        text = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        self._set_countdown(text, DANGER if remaining <= LOW_TIME_SECONDS else TEXT)

    def _set_countdown(self, text: str, color: str) -> None:
        self.countdown_label.setText(text)
        self.countdown_label.setStyleSheet(
            f"font-size: 56px; font-weight: 700; color: {color};"
        )

    # --- Eğitmen butonları ---

    def _extend_5(self) -> None:
        self._extend(5)

    def _extend_10(self) -> None:
        self._extend(10)

    def _extend(self, minutes: int) -> None:
        if self.snapshot is None:
            return
        try:
            self.ends_at = self.server.extend_exam(self.snapshot.exam_id, minutes)
        except ExamSessionError as error:
            QMessageBox.warning(self, "Süre eklenemedi", error.message)
            return
        except Exception:
            logger.exception("Süre eklenirken beklenmeyen hata")
            QMessageBox.critical(self, "Süre eklenemedi", "Beklenmeyen bir hata oluştu.")
            return
        self._update_header()
        self._tick()

    def _stop(self) -> None:
        if self.snapshot is None:
            return
        answer = QMessageBox.question(
            self, "Sınavı bitir",
            f"“{self.snapshot.title}” sınavı şimdi bitirilsin mi?\n\n"
            "Göndermemiş öğrencilerin kayıtlı cevapları otomatik gönderilecek. Bu işlem geri alınamaz.",
            defaultButton=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.server.stop_exam(self.snapshot.exam_id)
        except ExamSessionError as error:
            QMessageBox.warning(self, "Sınav bitirilemedi", error.message)
        except Exception:
            logger.exception("Sınav bitirilirken beklenmeyen hata")
            QMessageBox.critical(self, "Sınav bitirilemedi", "Beklenmeyen bir hata oluştu.")
        self.load(self.snapshot.exam_id if self.snapshot else None)

    # --- Sunucu olayları (ServerBridge sinyalleri, UI thread'inde çalışır) ---

    def on_student_connected(self, student: ConnectedStudent) -> None:
        state = self.states.get(student.username)
        if state is None:
            return  # bu sınavın sınıfında değil
        state.connected = True
        state.ip = student.ip
        state.last_activity = utcnow()
        self._changed(student.username)

    def on_student_disconnected(self, student: ConnectedStudent) -> None:
        state = self.states.get(student.username)
        if state is None:
            return
        state.connected = False
        self._changed(student.username)

    def on_answer_saved(self, student: ConnectedStudent, exam_id: int, answered_count: int) -> None:
        state = self._state_for(student.username, exam_id)
        if state is None:
            return
        state.answered_count = answered_count
        state.last_activity = utcnow()
        self._changed(student.username)

    def on_submitted(self, username: str, exam_id: int, auto_submitted: bool) -> None:
        state = self._state_for(username, exam_id)
        if state is None:
            return
        state.submitted = True
        state.last_activity = utcnow()
        self._changed(username)

    def on_focus_lost(self, student: ConnectedStudent, exam_id: int) -> None:
        state = self._state_for(student.username, exam_id)
        if state is None:
            return
        state.focus_lost_count += 1
        self._changed(student.username)

    def on_exam_finished(self, exam_id: int, reason: str) -> None:
        if self.snapshot is not None and self.snapshot.exam_id == exam_id:
            self.load(exam_id)  # durum 'finished', otomatik gönderilenler 'Gönderdi'
            self.info_label.setText(
                f"{self.info_label.text()} · Sınav bitti ({FINISH_REASONS.get(reason, reason)})"
            )
        self.refresh_exam_list()

    def _state_for(self, username: str, exam_id: int) -> StudentState | None:
        """Olay şu an gösterilen sınava aitse öğrencinin durumunu döner."""
        if self.snapshot is None or self.snapshot.exam_id != exam_id:
            return None
        return self.states.get(username)

    def _changed(self, username: str) -> None:
        """Öğrenciyi kirli işaretler; tablo kısa süre sonra toplu yenilenir."""
        self.dirty.add(username)
        if not self.flush_timer.isActive():
            self.flush_timer.start()

    def flush_pending(self) -> None:
        """Bekleyen tüm satır değişikliklerini tabloya yazar ve sayaçları günceller."""
        self.flush_timer.stop()
        if not self.dirty:
            return
        for username in self.dirty:
            if username in self.rows:
                self._update_row(username)
        self.dirty.clear()
        self._update_counters()

    # --- Testler ve dışarısı için okuma ---

    def status_of(self, username: str) -> str:
        return compute_status(self.states[username], self._exam_running())
