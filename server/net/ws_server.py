"""WebSocket sunucusu. (Sahibi: A)

- Kendi asyncio döngüsüyle AYRI BİR THREAD'de çalışır, böylece Qt arayüzü donmaz.
- Gelen her mesaj tipine göre HANDLERS sözlüğündeki fonksiyon çağrılır.
  Yeni mesaj tipi eklemek: `async def handle_xxx(server, client, envelope)` yaz,
  HANDLERS sözlüğüne ekle. Giriş gerektirmiyorsa PUBLIC_TYPES'a da ekle.
- Arayüze haber vermek için ServerObserver kullanılır. DİKKAT: observer metotları
  sunucu thread'inde çağrılır; Qt tarafı bunları Signal'e çevirmelidir
  (bkz. instructor_app/server_bridge.py).

Kullanım:
    server = start_server(observer)   # port doluysa OSError fırlatır
    ...
    server.stop()
"""

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from server.db.models import utcnow
from server.services.auth import authenticate
from shared import config
from shared.protocol import (
    Envelope,
    ErrorCode,
    LoginOk,
    LoginRequest,
    MsgType,
    Pong,
    ProtocolError,
    UserInfo,
    decode,
    encode,
    make_error,
    parse_payload,
)

logger = logging.getLogger(__name__)

# Aynı öğrenci başka yerden girince eski bağlantıyı bu kodla kapatırız.
CLOSE_DUPLICATE_SESSION = 4001


@dataclass(frozen=True)
class ConnectedStudent:
    """Giriş yapmış bir öğrencinin özeti (arayüzde göstermek için)."""

    user_id: int
    username: str
    full_name: str
    class_name: str | None
    ip: str
    connected_at: datetime


class ServerObserver(Protocol):
    """Sunucudaki olaylardan haberdar olmak isteyenler bu metotları yazar."""

    def on_student_connected(self, student: ConnectedStudent) -> None: ...

    def on_student_disconnected(self, student: ConnectedStudent) -> None: ...


@dataclass
class ClientState:
    """Tek bir WebSocket bağlantısının durumu."""

    websocket: ServerConnection
    ip: str
    student: ConnectedStudent | None = None  # giriş yapınca dolar
    extra: dict = field(default_factory=dict)  # ileride modüller kendi verilerini koyabilir

    async def send(self, text: str) -> None:
        try:
            await self.websocket.send(text)
        except ConnectionClosed:
            pass  # bağlantı kopmuş; temizlik _handle_connection'da yapılır

    async def send_error(self, code: str, message: str, msg_id: str | None) -> None:
        await self.send(make_error(code, message, msg_id))


class WsServer:
    def __init__(
        self,
        observer: ServerObserver | None = None,
        host: str = "0.0.0.0",
        port: int = config.WS_PORT,
    ) -> None:
        self.observer = observer
        self.host = host
        self.port = port  # port=0 verilirse start() sonrası gerçek port yazılır
        self._sessions: dict[str, ClientState] = {}  # username -> bağlantı
        self._lock = threading.Lock()                # _sessions Qt thread'inden de okunur
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_future: asyncio.Future | None = None
        self._ready = threading.Event()
        self._start_error: OSError | None = None
        self._background_tasks: set[asyncio.Task] = set()  # çöp toplayıcı silmesin diye

    # ------------------------------------------------------------------
    # Başlatma / durdurma (Qt thread'inden çağrılır)
    # ------------------------------------------------------------------

    def start(self, timeout: float = 5.0) -> None:
        """Sunucuyu ayrı thread'de başlatır ve dinlemeye başlayana kadar bekler."""
        self._thread = threading.Thread(target=self._run, name="WsServer", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise OSError("Sunucu zamanında başlatılamadı.")
        if self._start_error is not None:
            raise self._start_error

    def stop(self) -> None:
        """Tüm bağlantıları kapatıp sunucuyu durdurur."""
        if self._loop is not None and self._stop_future is not None:
            self._loop.call_soon_threadsafe(self._finish)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def connected_students(self) -> list[ConnectedStudent]:
        """Şu an bağlı ve giriş yapmış öğrenciler (her thread'den çağrılabilir)."""
        with self._lock:
            return [c.student for c in self._sessions.values() if c.student is not None]

    # ------------------------------------------------------------------
    # Sunucu thread'i
    # ------------------------------------------------------------------

    def _finish(self) -> None:
        if self._stop_future is not None and not self._stop_future.done():
            self._stop_future.set_result(None)

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_future = self._loop.create_future()
        try:
            async with serve(
                self._handle_connection, self.host, self.port, max_size=config.MAX_MESSAGE_BYTES
            ) as ws_server:
                self.port = ws_server.sockets[0].getsockname()[1]
                self._ready.set()
                await self._stop_future
        except OSError as exc:
            self._start_error = exc
            self._ready.set()

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        client = ClientState(websocket=websocket, ip=websocket.remote_address[0])
        try:
            async for raw in websocket:
                await self._dispatch(client, raw)
        except ConnectionClosed:
            pass
        finally:
            self._unregister(client)

    async def _dispatch(self, client: ClientState, raw: str | bytes) -> None:
        """Gelen mesajı çözer ve uygun handler'a yönlendirir."""
        msg_id = None
        try:
            envelope = decode(raw)
            msg_id = envelope.id
            if client.student is None and envelope.type not in PUBLIC_TYPES:
                await client.send_error(
                    ErrorCode.NOT_AUTHENTICATED, "Önce giriş yapmalısınız.", msg_id
                )
                return
            handler = HANDLERS.get(envelope.type)
            if handler is None:
                await client.send_error(
                    ErrorCode.UNKNOWN_TYPE, "Bu istek sunucu tarafından desteklenmiyor.", msg_id
                )
                return
            await handler(self, client, envelope)
        except ProtocolError as exc:
            await client.send_error(exc.code, exc.message, msg_id)
        except Exception:
            logger.exception("Mesaj işlenirken beklenmeyen hata")
            await client.send_error(
                ErrorCode.INTERNAL, "Sunucuda beklenmeyen bir hata oluştu.", msg_id
            )

    # ------------------------------------------------------------------
    # Oturum kaydı
    # ------------------------------------------------------------------

    async def register(self, client: ClientState, student: ConnectedStudent) -> None:
        """Girişi kaydeder. Aynı öğrenci başka yerden bağlıysa eski bağlantıyı kapatır."""
        with self._lock:
            old = self._sessions.get(student.username)
            client.student = student
            self._sessions[student.username] = client
        if old is not None and old is not client:
            # TODO(P1): event_log ile 'duplicate_session' olayı loglanacak.
            # Kapatmayı beklemeyiz: eski bilgisayar ağdan kopmuşsa kapanma 10 sn sürebilir.
            task = asyncio.create_task(
                old.websocket.close(CLOSE_DUPLICATE_SESSION, "Bu hesapla başka bir yerden giriş yapıldı.")
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            self._notify("on_student_disconnected", old.student)
        self._notify("on_student_connected", student)

    def _unregister(self, client: ClientState) -> None:
        if client.student is None:
            return
        with self._lock:
            # Yerine yeni bağlantı geçtiyse (duplicate) kaydı silme.
            if self._sessions.get(client.student.username) is not client:
                return
            del self._sessions[client.student.username]
        # TODO(P1): event_log ile 'disconnected' olayı loglanacak.
        self._notify("on_student_disconnected", client.student)

    def _notify(self, method: str, student: ConnectedStudent | None) -> None:
        if self.observer is None or student is None:
            return
        try:
            getattr(self.observer, method)(student)
        except Exception:
            logger.exception("Observer hatası: %s", method)


def start_server(observer: ServerObserver | None = None, port: int = config.WS_PORT) -> WsServer:
    """Sunucuyu oluşturup başlatır. Port kullanımdaysa OSError fırlatır."""
    server = WsServer(observer=observer, port=port)
    server.start()
    return server


# ----------------------------------------------------------------------
# Mesaj handler'ları
# ----------------------------------------------------------------------

Handler = Callable[[WsServer, ClientState, Envelope], Awaitable[None]]


async def handle_login(server: WsServer, client: ClientState, envelope: Envelope) -> None:
    request = parse_payload(envelope)
    assert isinstance(request, LoginRequest)
    if client.student is not None:
        await client.send_error(ErrorCode.BAD_REQUEST, "Zaten giriş yapılmış.", envelope.id)
        return

    # bcrypt yavaştır; ayrı thread'de çalıştır ki diğer öğrenciler beklemesin.
    user = await asyncio.to_thread(authenticate, request.username, request.password)
    if user is None:
        # TODO(P1): event_log ile 'login_failed' olayı loglanacak.
        await client.send_error(
            ErrorCode.INVALID_CREDENTIALS, "Öğrenci numarası veya şifre hatalı.", envelope.id
        )
        return
    if user.role != "student":
        await client.send_error(
            ErrorCode.NOT_STUDENT, "Bu uygulamaya yalnızca öğrenciler giriş yapabilir.", envelope.id
        )
        return

    class_name = user.school_class.name if user.school_class else None
    student = ConnectedStudent(
        user_id=user.id, username=user.username, full_name=user.full_name,
        class_name=class_name, ip=client.ip, connected_at=utcnow(),
    )
    await server.register(client, student)
    # TODO(P1): event_log 'login'; aktif sınav varsa exam_start gönderilecek.
    user_info = UserInfo(
        id=user.id, username=user.username, full_name=user.full_name, class_name=class_name
    )
    await client.send(encode(MsgType.LOGIN_OK, LoginOk(user=user_info), envelope.id))


async def handle_ping(server: WsServer, client: ClientState, envelope: Envelope) -> None:
    await client.send(encode(MsgType.PONG, Pong(server_now=utcnow()), envelope.id))


# Mesaj tipi -> handler. Yeni mesaj tipleri buraya eklenir.
HANDLERS: dict[str, Handler] = {
    MsgType.LOGIN: handle_login,
    MsgType.PING: handle_ping,
}

# Giriş yapmadan gönderilebilen mesaj tipleri.
PUBLIC_TYPES: set[str] = {MsgType.LOGIN, MsgType.PING}
