"""Sunucusuz deneme modu: python -m student_app.main --demo  (Sahibi: C)

DemoBackend, gerçek ServerClient ile AYNI sinyallere sahip sahte bir sunucudur.
Pencere (main.py) hangisiyle çalıştığını bilmez; böylece --demo'da gördüğün akış
gerçek sınavdaki akışın aynısıdır. Cevaplar sadece bellekte tutulur.
"""

import json
from datetime import timedelta
from functools import partial
from pathlib import Path

from pydantic import BaseModel
from PySide6.QtCore import QObject, QTimer, Signal

from shared.protocol import (
    ExamEnd,
    ExamStart,
    MsgType,
    SaveAnswerRequest,
    SaveOk,
    SubmitOk,
    UserInfo,
)
from student_app.net.client import ConnectionState
from student_app.net.server_clock import ServerClock

DEMO_EXAM_PATH = Path(__file__).with_name("demo_exam.json")
DEMO_USER = UserInfo(id=0, username="260101001", full_name="Demo Öğrenci", class_name="1. Öğretim A")
FAKE_SAVE_DELAY_MS = 300  # gerçek ağdaki gecikmeyi taklit eder


def load_demo_exam(minutes: float, clock: ServerClock) -> ExamStart:
    """demo_exam.json'u okur; bitiş saatini şimdiden 'minutes' dakika sonrası yapar."""
    data = json.loads(DEMO_EXAM_PATH.read_text(encoding="utf-8"))
    now = clock.now()
    data["server_now"] = now.isoformat()
    data["ends_at"] = (now + timedelta(minutes=minutes)).isoformat()
    return ExamStart.model_validate(data)


class DemoBackend(QObject):
    # ServerClient ile aynı sinyaller (main.py hepsine bağlanır)
    logged_in = Signal(object)
    login_failed = Signal(str)
    exam_started = Signal(object)
    exam_updated = Signal(object)
    exam_ended = Signal(object)
    save_confirmed = Signal(object)
    submit_confirmed = Signal(object)
    error_received = Signal(str, str, str)
    connection_changed = Signal(str)
    connection_error = Signal(str)
    connection_lost = Signal(str)
    session_replaced = Signal()

    def __init__(self, minutes: float, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.clock = ServerClock()
        self.clock.update(self.clock.now())  # demo'da sunucu saati = bilgisayar saati
        self.saved: dict[int, SaveAnswerRequest] = {}
        self._minutes = minutes
        self._exam: ExamStart | None = None
        self._end_timer = QTimer(self)
        self._end_timer.setSingleShot(True)
        self._end_timer.timeout.connect(self._on_time_up)

    @property
    def is_connected(self) -> bool:
        return True

    def start(self) -> None:
        """Girişi ve sınav başlangıcını taklit eder."""
        self._exam = load_demo_exam(self._minutes, self.clock)
        self.connection_changed.emit(ConnectionState.CONNECTED)
        self.logged_in.emit(DEMO_USER)
        self.exam_started.emit(self._exam)
        self._end_timer.start(int(self._minutes * 60_000))

    def login(self, host: str, port: int, username: str, password: str) -> None:
        self.logged_in.emit(DEMO_USER)

    def request(self, msg_type: str, payload: BaseModel | None = None) -> str:
        if isinstance(payload, SaveAnswerRequest):
            self.saved[payload.question_id] = payload
            reply = SaveOk(question_id=payload.question_id, saved_at=self.clock.now())
            # context (self) verilir: nesne silinirse zamanlayıcı da iptal olur
            QTimer.singleShot(FAKE_SAVE_DELAY_MS, self, partial(self.save_confirmed.emit, reply))
        elif msg_type == MsgType.SUBMIT:
            self._end_timer.stop()
            reply = SubmitOk(submitted_at=self.clock.now())
            QTimer.singleShot(FAKE_SAVE_DELAY_MS, self, partial(self.submit_confirmed.emit, reply))
        return "demo"

    def send_focus_lost(self, exam_id: int) -> None:
        pass  # demo'da loglanacak sunucu yok

    def close(self) -> None:
        self._end_timer.stop()

    def _on_time_up(self) -> None:
        assert self._exam is not None
        self.exam_ended.emit(ExamEnd(exam_id=self._exam.exam.id, reason="time_up"))
