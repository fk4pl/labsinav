"""Sunucu thread'i ile Qt arayüzü arasındaki köprü.

Sunucu observer metotlarını KENDİ thread'inde çağırır. Qt widget'ları ise sadece
ana thread'den değiştirilebilir. Signal'ler thread'ler arasında güvenlidir:
emit() sunucu thread'inde yapılır, bağlı slot ana thread'de çalışır.
"""

from PySide6.QtCore import QObject, Signal

from server.net.ws_server import ConnectedStudent


class ServerBridge(QObject):
    student_connected = Signal(object)     # ConnectedStudent
    student_disconnected = Signal(object)  # ConnectedStudent

    def on_student_connected(self, student: ConnectedStudent) -> None:
        self.student_connected.emit(student)

    def on_student_disconnected(self, student: ConnectedStudent) -> None:
        self.student_disconnected.emit(student)
