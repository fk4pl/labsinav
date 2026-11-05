"""Sunucu thread'i ile Qt arayüzü arasındaki köprü.

Sunucu observer metotlarını KENDİ thread'inde çağırır. Qt widget'ları ise sadece
ana thread'den değiştirilebilir. Signal'ler thread'ler arasında güvenlidir:
emit() sunucu thread'inde yapılır, bağlı slot ana thread'de çalışır.
"""

from PySide6.QtCore import QObject, Signal

from server.net.ws_server import ConnectedStudent


class ServerBridge(QObject):
    student_connected = Signal(object)          # ConnectedStudent
    student_disconnected = Signal(object)       # ConnectedStudent
    answer_saved = Signal(object, int, int)     # ConnectedStudent, exam_id, answered_count
    submitted = Signal(str, int, bool)          # username, exam_id, auto_submitted
    exam_finished = Signal(int, str)            # exam_id, reason ("time_up" | "instructor_stopped")

    def on_student_connected(self, student: ConnectedStudent) -> None:
        self.student_connected.emit(student)

    def on_student_disconnected(self, student: ConnectedStudent) -> None:
        self.student_disconnected.emit(student)

    def on_answer_saved(self, student: ConnectedStudent, exam_id: int, answered_count: int) -> None:
        self.answer_saved.emit(student, exam_id, answered_count)

    def on_submitted(self, username: str, exam_id: int, auto_submitted: bool) -> None:
        self.submitted.emit(username, exam_id, auto_submitted)

    def on_exam_finished(self, exam_id: int, reason: str) -> None:
        self.exam_finished.emit(exam_id, reason)
