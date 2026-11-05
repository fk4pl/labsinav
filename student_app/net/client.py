"""Öğrenci uygulamasının sunucuyla konuşan istemcisi. (Sahibi: C)

QWebSocket Qt'nin olay döngüsüyle çalışır: ayrı thread gerekmez, arayüz donmaz.
Arayüz bu sınıfın sinyallerine bağlanır:
    connected()                  -> bağlantı kuruldu
    disconnected(str)            -> bağlantı koptu (sebep, Türkçe)
    message_received(Envelope)   -> sunucudan mesaj geldi
    connection_error(str)        -> bağlanılamadı (Türkçe mesaj)
"""

import logging

from pydantic import BaseModel
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from shared import config
from shared.protocol import MsgType, PingRequest, ProtocolError, decode, encode, new_id

logger = logging.getLogger(__name__)

# server/net/ws_server.py içindeki CLOSE_DUPLICATE_SESSION ile aynı değer.
CLOSE_DUPLICATE_SESSION = 4001
CONNECT_TIMEOUT_MS = 5000  # yanlış IP girilirse bu süre sonunda vazgeç


class ServerClient(QObject):
    connected = Signal()
    disconnected = Signal(str)
    message_received = Signal(object)
    connection_error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.host: str | None = None
        self.port: int | None = None
        self._is_connected = False
        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message)
        self._socket.errorOccurred.connect(self._on_error)

        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(config.PING_INTERVAL_SEC * 1000)
        self._ping_timer.timeout.connect(self._send_ping)

        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.setInterval(CONNECT_TIMEOUT_MS)
        self._connect_timer.timeout.connect(self._on_connect_timeout)

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def connect_to(self, host: str, port: int) -> None:
        """Sunucuya bağlanmayı başlatır; sonuç sinyallerle bildirilir."""
        self.close()
        self.host, self.port = host, port
        self._connect_timer.start()
        self._socket.open(QUrl(f"ws://{host}:{port}"))

    def close(self) -> None:
        self._ping_timer.stop()
        self._connect_timer.stop()
        if self._socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self._socket.close()

    def send(self, msg_type: str, payload: BaseModel | None = None) -> str | None:
        """Mesaj yollar ve id'sini döner (cevabı eşleştirmek için). Bağlı değilse None."""
        if not self._is_connected:
            return None
        msg_id = new_id()
        self._socket.sendTextMessage(encode(msg_type, payload, msg_id))
        return msg_id

    # --- QWebSocket olayları ---

    def _on_connected(self) -> None:
        self._connect_timer.stop()
        self._is_connected = True
        self._ping_timer.start()
        self.connected.emit()

    def _on_disconnected(self) -> None:
        self._ping_timer.stop()
        if not self._is_connected:
            return  # hiç bağlanamadık; kullanıcıya _on_error haber verdi
        self._is_connected = False
        if self._socket.closeCode().value == CLOSE_DUPLICATE_SESSION:  # closeCode() enum döner
            reason = "Bu hesapla başka bir bilgisayardan giriş yapıldı."
        else:
            reason = "Sunucuyla bağlantı koptu."
        self.disconnected.emit(reason)

    def _on_error(self, error: QAbstractSocket.SocketError) -> None:
        logger.info("WebSocket hatası: %s (%s)", error, self._socket.errorString())
        if self._is_connected or not self._connect_timer.isActive():
            return  # bağlıyken oluşan hata disconnected olarak gelir; zaman aşımı ise zaten bildirildi
        self._connect_timer.stop()
        if error == QAbstractSocket.SocketError.ConnectionRefusedError:
            message = "Sunucuya bağlanılamadı. Eğitmen uygulamasının açık olduğundan emin olun."
        elif error == QAbstractSocket.SocketError.HostNotFoundError:
            message = "Sunucu adresi bulunamadı. IP adresini kontrol edin."
        else:
            message = "Sunucuya bağlanılamadı. Ağ bağlantınızı ve IP adresini kontrol edin."
        self.connection_error.emit(message)

    def _on_connect_timeout(self) -> None:
        self._socket.abort()
        self.connection_error.emit(
            "Sunucuya bağlanılamadı (zaman aşımı). IP adresini ve ağ bağlantınızı kontrol edin."
        )

    def _on_text_message(self, text: str) -> None:
        try:
            envelope = decode(text)
        except ProtocolError:
            logger.warning("Sunucudan çözülemeyen mesaj geldi")
            return
        self.message_received.emit(envelope)

    def _send_ping(self) -> None:
        self.send(MsgType.PING, PingRequest())

