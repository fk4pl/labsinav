"""Öğrenci uygulamasının sunucuyla konuşan istemcisi. (Sahibi: C)

QWebSocket Qt'nin olay döngüsüyle çalışır: ayrı thread gerekmez, arayüz donmaz.
Sunucudan gelen her mesaj tipi için ayrı bir sinyal vardır; arayüz bunlara bağlanır.

Yeniden bağlanma:
    Giriş başarılı olduktan sonra bağlantı koparsa istemci 1, 2, 4, 8, 15, 15… saniye
    bekleyerek tekrar bağlanmayı dener ve kayıtlı bilgilerle otomatik giriş yapar.
    Sunucu, aktif sınav varsa exam_start'ı kayıtlı cevaplarla tekrar gönderir.
    Başka bir bilgisayardan aynı hesapla girilirse (close code 4001) tekrar denenmez.

Ölü bağlantı tespiti:
    WiFi koptuğunda işletim sistemi bunu bazen dakikalarca fark etmez. Bu yüzden
    PONG_TIMEOUT_SEC boyunca sunucudan hiçbir mesaj gelmezse bağlantıyı kendimiz keseriz.
"""

import logging
import random
import time

from pydantic import BaseModel
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from shared import config
from shared.protocol import (
    Envelope,
    ErrorPayload,
    ExamStart,
    ExamUpdate,
    FocusLostRequest,
    LoginOk,
    LoginRequest,
    MsgType,
    PingRequest,
    Pong,
    ProtocolError,
    decode,
    encode,
    new_id,
    parse_payload,
)
from student_app.net.server_clock import ServerClock

logger = logging.getLogger(__name__)

# server/net/ws_server.py içindeki CLOSE_DUPLICATE_SESSION ile aynı değer.
CLOSE_DUPLICATE_SESSION = 4001
CONNECT_TIMEOUT_MS = 5000          # yanlış IP girilirse bu süre sonunda vazgeç
PONG_TIMEOUT_SEC = 25              # bu süre sunucudan ses çıkmazsa bağlantı ölü sayılır
RECONNECT_DELAYS_SEC = [1, 2, 4, 8, 15]  # son değer tekrar tekrar kullanılır


class ConnectionState:
    CONNECTED = "connected"        # bağlı ve giriş yapılmış
    RECONNECTING = "reconnecting"  # koptu, tekrar deniyoruz
    OFFLINE = "offline"            # bağlı değil, denemiyoruz


class ServerClient(QObject):
    # Giriş
    logged_in = Signal(object)            # UserInfo
    login_failed = Signal(str)            # Türkçe mesaj
    # Sınav
    exam_started = Signal(object)         # ExamStart
    exam_updated = Signal(object)         # ExamUpdate
    exam_ended = Signal(object)           # ExamEnd
    save_confirmed = Signal(object)       # SaveOk
    submit_confirmed = Signal(object)     # SubmitOk
    error_received = Signal(str, str, str)  # (code, message, isteğin tipi)
    # Bağlantı
    connection_changed = Signal(str)      # ConnectionState değeri
    connection_error = Signal(str)        # ilk bağlantı kurulamadı (giriş ekranında gösterilir)
    connection_lost = Signal(str)         # koptu ve tekrar denenmeyecek (sebep, Türkçe)
    session_replaced = Signal()           # aynı hesapla başka yerden giriş yapıldı

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.host: str | None = None
        self.port: int | None = None
        self.clock = ServerClock()

        self._socket_open = False         # WebSocket bağlı mı
        self._credentials: LoginRequest | None = None
        self._logged_in_once = False      # en az bir kez başarıyla giriş yapıldı mı (otomatik yeniden giriş için)
        self._reconnecting = False
        self._attempt = 0
        self._pending: dict[str, str] = {}  # mesaj id -> istek tipi (cevabı eşleştirmek için)
        self._last_received = time.monotonic()

        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message)
        self._socket.errorOccurred.connect(self._on_error)

        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(config.PING_INTERVAL_SEC * 1000)
        self._ping_timer.timeout.connect(self._on_ping_tick)

        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.setInterval(CONNECT_TIMEOUT_MS)
        self._connect_timer.timeout.connect(self._on_connect_timeout)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._open_socket)

        # Mesaj tipi -> o mesaj gelince yayılacak sinyal
        self._signal_by_type = {
            MsgType.EXAM_START: self.exam_started,
            MsgType.EXAM_UPDATE: self.exam_updated,
            MsgType.EXAM_END: self.exam_ended,
            MsgType.SAVE_OK: self.save_confirmed,
            MsgType.SUBMIT_OK: self.submit_confirmed,
        }

    # ------------------------------------------------------------------
    # Dışarıdan çağrılanlar
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._socket_open

    def login(self, host: str, port: int, username: str, password: str) -> None:
        """Gerekirse bağlanır ve giriş yapar. Sonuç: logged_in / login_failed / connection_error."""
        self._credentials = LoginRequest(username=username, password=password)
        self._logged_in_once = False
        if self._socket_open and (self.host, self.port) == (host, port):
            self._send_login()
            return
        self.close()
        self.host, self.port = host, port
        self._open_socket()

    def request(self, msg_type: str, payload: BaseModel | None = None) -> str | None:
        """İstek yollar ve id'sini döner. Bağlı değilse None (istek gönderilmedi)."""
        if not self._socket_open:
            return None
        msg_id = new_id()
        self._pending[msg_id] = msg_type
        self._socket.sendTextMessage(encode(msg_type, payload, msg_id))
        return msg_id

    def send_focus_lost(self, exam_id: int) -> None:
        """Öğrenci pencereden çıktı. Sunucu cevap vermez, sadece loglar."""
        if self._socket_open:
            payload = FocusLostRequest(exam_id=exam_id, at=self.clock.now())
            self._socket.sendTextMessage(encode(MsgType.FOCUS_LOST, payload))

    def close(self) -> None:
        """Bağlantıyı kapatır ve yeniden bağlanmayı durdurur (çıkış / pencere kapanışı)."""
        self._stop_reconnecting()
        self._logged_in_once = False
        self._ping_timer.stop()
        self._connect_timer.stop()
        self._socket_open = False
        self._pending.clear()
        if self._socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self._socket.abort()

    # ------------------------------------------------------------------
    # Bağlanma ve yeniden bağlanma
    # ------------------------------------------------------------------

    def _open_socket(self) -> None:
        self._connect_timer.start()
        self._socket.open(QUrl(f"ws://{self.host}:{self.port}"))

    def _schedule_reconnect(self) -> None:
        delay = RECONNECT_DELAYS_SEC[min(self._attempt, len(RECONNECT_DELAYS_SEC) - 1)]
        delay += random.uniform(0, 1)  # 40 öğrenci aynı saniyede saldırmasın
        self._attempt += 1
        logger.info("Yeniden bağlanma denemesi %d, %.1f sn sonra", self._attempt, delay)
        self._reconnect_timer.start(int(delay * 1000))

    def _stop_reconnecting(self) -> None:
        self._reconnecting = False
        self._attempt = 0
        self._reconnect_timer.stop()

    def _give_up(self, reason: str) -> None:
        """Bağlantı koptu ve bir daha denemeyeceğiz."""
        self._stop_reconnecting()
        self._logged_in_once = False
        self.connection_changed.emit(ConnectionState.OFFLINE)
        self.connection_lost.emit(reason)

    # ------------------------------------------------------------------
    # QWebSocket olayları
    # ------------------------------------------------------------------

    def _on_connected(self) -> None:
        self._connect_timer.stop()
        self._socket_open = True
        self._last_received = time.monotonic()
        self._ping_timer.start()
        if self._credentials is not None:
            self._send_login()

    def _on_disconnected(self) -> None:
        self._ping_timer.stop()
        self._pending.clear()
        if not self._socket_open:
            return  # hiç bağlanamadık; _on_error / _on_connect_timeout ilgilendi
        self._socket_open = False
        if self._socket.closeCode().value == CLOSE_DUPLICATE_SESSION:  # closeCode() enum döner
            self._stop_reconnecting()
            self._logged_in_once = False
            self.connection_changed.emit(ConnectionState.OFFLINE)
            self.session_replaced.emit()
        elif self._logged_in_once:
            self._reconnecting = True
            self.connection_changed.emit(ConnectionState.RECONNECTING)
            self._schedule_reconnect()
        else:
            self._give_up("Sunucuyla bağlantı koptu.")

    def _on_error(self, error: QAbstractSocket.SocketError) -> None:
        logger.info("WebSocket hatası: %s (%s)", error, self._socket.errorString())
        if self._socket_open or not self._connect_timer.isActive():
            return  # bağlıyken oluşan hata disconnected olarak gelir; zaman aşımı ise zaten işlendi
        self._connect_timer.stop()
        self._connect_failed(self._connect_error_message(error))

    def _on_connect_timeout(self) -> None:
        self._socket.abort()
        self._connect_failed(
            "Sunucuya bağlanılamadı (zaman aşımı). IP adresini ve ağ bağlantınızı kontrol edin."
        )

    def _connect_failed(self, message: str) -> None:
        if self._reconnecting:
            self._schedule_reconnect()  # sessizce tekrar dene
        else:
            self._credentials = None
            self.connection_error.emit(message)

    @staticmethod
    def _connect_error_message(error: QAbstractSocket.SocketError) -> str:
        if error == QAbstractSocket.SocketError.ConnectionRefusedError:
            return "Sunucuya bağlanılamadı. Eğitmen uygulamasının açık olduğundan emin olun."
        if error == QAbstractSocket.SocketError.HostNotFoundError:
            return "Sunucu adresi bulunamadı. IP adresini kontrol edin."
        return "Sunucuya bağlanılamadı. Ağ bağlantınızı ve IP adresini kontrol edin."

    def _on_ping_tick(self) -> None:
        if time.monotonic() - self._last_received > PONG_TIMEOUT_SEC:
            logger.info("Sunucudan %d sn ses yok; bağlantı ölü sayılıyor", PONG_TIMEOUT_SEC)
            self._socket.abort()  # disconnected sinyali -> yeniden bağlanma
            return
        self.request(MsgType.PING, PingRequest())

    def _send_login(self) -> None:
        assert self._credentials is not None
        self.request(MsgType.LOGIN, self._credentials)

    # ------------------------------------------------------------------
    # Gelen mesajlar
    # ------------------------------------------------------------------

    def _on_text_message(self, text: str) -> None:
        self._last_received = time.monotonic()
        try:
            envelope = decode(text)
            payload = parse_payload(envelope)
        except ProtocolError:
            logger.warning("Sunucudan çözülemeyen mesaj geldi")
            return
        request_type = self._pending.pop(envelope.id, "") if envelope.id else ""
        self._dispatch(envelope, payload, request_type)

    def _dispatch(self, envelope: Envelope, payload: BaseModel, request_type: str) -> None:
        """Mesajı tipine göre doğru sinyale yönlendirir."""
        if isinstance(payload, (ExamStart, ExamUpdate, Pong)):
            self.clock.update(payload.server_now)  # geri sayım sunucu saatine göre olsun

        if isinstance(payload, LoginOk):
            self._on_login_ok(payload)
        elif isinstance(payload, ErrorPayload):
            self._on_error_message(payload, request_type)
        elif envelope.type in self._signal_by_type:
            self._signal_by_type[envelope.type].emit(payload)
        # pong: saat yukarıda güncellendi, başka iş yok

    def _on_login_ok(self, payload: LoginOk) -> None:
        self._logged_in_once = True
        self._stop_reconnecting()
        self.connection_changed.emit(ConnectionState.CONNECTED)
        self.logged_in.emit(payload.user)

    def _on_error_message(self, payload: ErrorPayload, request_type: str) -> None:
        if request_type != MsgType.LOGIN:
            self.error_received.emit(payload.code, payload.message, request_type)
            return
        if self._logged_in_once or self._reconnecting:
            # Otomatik yeniden girişte hata (ör. şifre değiştirildi): öğrenci elle girmeli.
            self.close()
            self._give_up(f"Tekrar giriş yapılamadı: {payload.message}")
        else:
            self._credentials = None
            self.login_failed.emit(payload.message)
