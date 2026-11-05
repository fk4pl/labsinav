"""WebSocket sunucusu. (Sahibi: A)

- Kendi asyncio döngüsüyle AYRI BİR THREAD'de çalışır, böylece Qt arayüzü donmaz.
- Gelen her mesaj tipine göre HANDLERS sözlüğündeki fonksiyon çağrılır.
  Yeni mesaj tipi eklemek: `async def handle_xxx(server, client, envelope)` yaz,
  HANDLERS sözlüğüne ekle. Giriş gerektirmiyorsa PUBLIC_TYPES'a da ekle.
- Kurallar (süre doldu mu, zaten gönderildi mi...) server/services/exam_session.py'dedir.
  Bu dosya sadece mesajları alır, servisi çağırır ve cevabı/yayını gönderir.
- Veri tabanı işleri asyncio.to_thread ile ayrı thread'de yapılır; böylece bir öğrencinin
  kaydı diğerlerini bekletmez.
- Arayüze haber vermek için ServerObserver kullanılır. DİKKAT: observer metotları
  sunucu thread'inde çağrılır; Qt tarafı bunları Signal'e çevirmelidir
  (bkz. instructor_app/server_bridge.py).

Kullanım:
    server = start_server(observer)   # port doluysa OSError fırlatır
    server.start_exam(exam_id)        # eğitmen arayüzünden (Qt thread'i)
    ...
    server.stop()
"""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, TypeVar

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from server.db.models import utcnow
from server.services import exam_session, grading
from server.services.auth import authenticate
from server.services.event_log import Event, log_event
from server.services.exam_session import ExamSessionError, FinishedExam
from shared import config
from shared.protocol import (
    Envelope,
    ErrorCode,
    ExamEnd,
    ExamUpdate,
    FocusLostRequest,
    LoginOk,
    LoginRequest,
    MsgType,
    Pong,
    ProtocolError,
    SaveAnswerRequest,
    SaveOk,
    SubmitOk,
    SubmitRequest,
    UserInfo,
    decode,
    encode,
    make_error,
    parse_payload,
)

logger = logging.getLogger(__name__)

# Aynı öğrenci başka yerden girince eski bağlantıyı bu kodla kapatırız.
CLOSE_DUPLICATE_SESSION = 4001

# Süresi dolan sınav kontrolü bu aralıkla yapılır (saniye).
EXAM_TICK_SEC = 1.0

# Qt thread'inden çağrılan işlemlerin en fazla bekleme süresi (saniye).
CALL_TIMEOUT_SEC = 30

T = TypeVar("T")


@dataclass(frozen=True)
class ConnectedStudent:
    """Giriş yapmış bir öğrencinin özeti (arayüzde göstermek için)."""

    user_id: int
    username: str
    full_name: str
    class_id: int | None
    class_name: str | None
    ip: str
    connected_at: datetime


class ServerObserver(Protocol):
    """Sunucudaki olaylardan haberdar olmak isteyenler bu metotları yazar.

    Hepsini yazmak zorunlu değildir; observer'da olmayan metot sessizce atlanır.
    """

    def on_student_connected(self, student: ConnectedStudent) -> None: ...

    def on_student_disconnected(self, student: ConnectedStudent) -> None: ...

    def on_answer_saved(self, student: ConnectedStudent, exam_id: int, answered_count: int) -> None: ...

    # Otomatik gönderilen öğrenci o an bağlı olmayabilir; bu yüzden sadece kullanıcı adı.
    def on_submitted(self, username: str, exam_id: int, auto_submitted: bool) -> None: ...

    def on_exam_finished(self, exam_id: int, reason: str) -> None: ...

    def on_focus_lost(self, student: ConnectedStudent, exam_id: int) -> None: ...


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
        clock: Callable[[], datetime] = utcnow,
        tick_interval: float = EXAM_TICK_SEC,
    ) -> None:
        self.observer = observer
        self.host = host
        self.port = port  # port=0 verilirse start() sonrası gerçek port yazılır
        self.clock = clock  # "şu an" — testler sahte saat verir
        self.tick_interval = tick_interval
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
    # Eğitmen işlemleri (Qt thread'inden çağrılır)
    # Hata olursa ExamSessionError fırlatır; arayüz exc.message'ı gösterir.
    # ------------------------------------------------------------------

    def start_exam(self, exam_id: int) -> datetime:
        """Sınavı başlatır, sınıftaki bağlı öğrencilere exam_start yollar. Bitiş saatini döner."""
        return self._call_in_loop(self._start_exam(exam_id))

    def extend_exam(self, exam_id: int, minutes: int) -> datetime:
        """Süre ekler, öğrencilere exam_update yollar. Yeni bitiş saatini döner."""
        return self._call_in_loop(self._extend_exam(exam_id, minutes))

    def stop_exam(self, exam_id: int) -> None:
        """Sınavı erken bitirir; gönderilmemiş cevaplar otomatik gönderilir."""
        self._call_in_loop(self._stop_exam(exam_id))

    def _call_in_loop(self, coro: Coroutine[Any, Any, T]) -> T:
        """Başka thread'den, sunucu thread'indeki asyncio döngüsünde iş çalıştırır ve bekler."""
        if self._loop is None or not self._loop.is_running():
            coro.close()
            raise ExamSessionError(ErrorCode.INTERNAL, "Sunucu çalışmıyor.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=CALL_TIMEOUT_SEC)

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
                ticker = asyncio.create_task(self._exam_ticker())
                self._ready.set()
                await self._stop_future
                ticker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticker
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
            await self._unregister(client)

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
        except ExamSessionError as exc:
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
            await self.log(
                Event.DUPLICATE_SESSION, username=student.username, ip=client.ip,
                detail=f"Eski bağlantı kapatıldı (eski IP: {old.ip})",
            )
            # Kapatmayı beklemeyiz: eski bilgisayar ağdan kopmuşsa kapanma 10 sn sürebilir.
            self._spawn(
                old.websocket.close(CLOSE_DUPLICATE_SESSION, "Bu hesapla başka bir yerden giriş yapıldı.")
            )
            self.notify("on_student_disconnected", old.student)
        self.notify("on_student_connected", student)

    async def _unregister(self, client: ClientState) -> None:
        if client.student is None:
            return
        with self._lock:
            # Yerine yeni bağlantı geçtiyse (duplicate) kaydı silme.
            if self._sessions.get(client.student.username) is not client:
                return
            del self._sessions[client.student.username]
        self.notify("on_student_disconnected", client.student)
        await self.log(Event.DISCONNECTED, username=client.student.username, ip=client.ip)

    def _clients_in_class(self, class_id: int) -> list[ClientState]:
        with self._lock:
            return [
                c for c in self._sessions.values()
                if c.student is not None and c.student.class_id == class_id
            ]

    # ------------------------------------------------------------------
    # Sınav akışı (sunucu thread'inde)
    # ------------------------------------------------------------------

    async def _start_exam(self, exam_id: int) -> datetime:
        started = await asyncio.to_thread(exam_session.start_exam, exam_id, self.clock())
        await self.log(Event.EXAM_STARTED, exam_id=exam_id, detail=f"Bitiş: {started.ends_at.isoformat()}")
        for client in self._clients_in_class(started.class_id):
            await self.send_exam_start(client, exam_id)
        return started.ends_at

    async def _extend_exam(self, exam_id: int, minutes: int) -> datetime:
        updated = await asyncio.to_thread(exam_session.extend_exam, exam_id, minutes, self.clock())
        await self.log(
            Event.EXAM_EXTENDED, exam_id=exam_id,
            detail=f"+{minutes} dk, yeni bitiş: {updated.ends_at.isoformat()}",
        )
        message = encode(
            MsgType.EXAM_UPDATE,
            ExamUpdate(exam_id=exam_id, ends_at=updated.ends_at, server_now=self.clock()),
        )
        for client in self._clients_in_class(updated.class_id):
            await client.send(message)
        return updated.ends_at

    async def _stop_exam(self, exam_id: int) -> None:
        finished = await asyncio.to_thread(exam_session.stop_exam, exam_id, self.clock())
        await self.log(Event.EXAM_STOPPED, exam_id=exam_id)
        await self._announce_finished(finished)

    async def _exam_ticker(self) -> None:
        """Saniyede bir süresi dolan sınavları bitirir.

        Süre veri tabanındaki ends_at'ten okunduğu için uygulama kapatılıp açılsa da
        sınav kaldığı yerden devam eder.
        """
        while True:
            try:
                finished_list = await asyncio.to_thread(exam_session.finish_expired_exams, self.clock())
                for finished in finished_list:
                    await self._announce_finished(finished)
            except Exception:
                logger.exception("Süre kontrolünde hata")
            await asyncio.sleep(self.tick_interval)

    async def _announce_finished(self, finished: FinishedExam) -> None:
        """Bitmiş sınav için: otomatik gönderimleri logla, exam_end yolla, puanlamayı başlat."""
        for item in finished.auto_submitted:
            await self.log(
                Event.AUTO_SUBMITTED, username=item.username, exam_id=finished.exam_id,
                detail=finished.reason,
            )
            self.notify("on_submitted", item.username, finished.exam_id, True)
        message = encode(MsgType.EXAM_END, ExamEnd(exam_id=finished.exam_id, reason=finished.reason))
        for client in self._clients_in_class(finished.class_id):
            await client.send(message)
        self.notify("on_exam_finished", finished.exam_id, finished.reason)
        self.grade_in_background([item.submission_id for item in finished.auto_submitted])

    async def send_exam_start(self, client: ClientState, exam_id: int) -> None:
        """Öğrenciyi sınava sokar ve exam_start (kayıtlı cevaplarla) gönderir."""
        assert client.student is not None
        exam_start = await asyncio.to_thread(
            exam_session.join_exam, exam_id, client.student.user_id, client.ip, self.clock()
        )
        await client.send(encode(MsgType.EXAM_START, exam_start))

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def grade_in_background(self, submission_ids: list[int]) -> None:
        """Puanlamayı arka planda, sırayla yapar. Bir hata diğerlerini durdurmaz."""
        if submission_ids:
            self._spawn(self._grade_all(submission_ids))

    async def _grade_all(self, submission_ids: list[int]) -> None:
        for submission_id in submission_ids:
            try:
                await asyncio.to_thread(grading.grade_submission, submission_id)
            except Exception:
                logger.exception("Puanlama hatası (submission %s)", submission_id)

    async def log(self, event: str, **fields: Any) -> None:
        """Olayı ayrı thread'de loglar (dosya + veri tabanı yazması döngüyü bekletmesin)."""
        await asyncio.to_thread(log_event, event, at=self.clock(), **fields)

    def notify(self, method: str, *args: Any) -> None:
        """Observer'a haber verir. Observer'da bu metot yoksa veya hata verirse atlanır."""
        if self.observer is None or any(arg is None for arg in args):
            return
        callback = getattr(self.observer, method, None)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.exception("Observer hatası: %s", method)

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)


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
        await server.log(
            Event.LOGIN_FAILED, username=request.username.strip(), ip=client.ip,
            detail="Hatalı kullanıcı adı veya şifre",
        )
        await client.send_error(
            ErrorCode.INVALID_CREDENTIALS, "Öğrenci numarası veya şifre hatalı.", envelope.id
        )
        return
    if user.role != "student":
        await server.log(
            Event.LOGIN_FAILED, username=user.username, ip=client.ip,
            detail="Öğrenci olmayan hesapla öğrenci uygulamasına giriş",
        )
        await client.send_error(
            ErrorCode.NOT_STUDENT, "Bu uygulamaya yalnızca öğrenciler giriş yapabilir.", envelope.id
        )
        return

    class_name = user.school_class.name if user.school_class else None
    student = ConnectedStudent(
        user_id=user.id, username=user.username, full_name=user.full_name,
        class_id=user.class_id, class_name=class_name, ip=client.ip, connected_at=server.clock(),
    )
    await server.register(client, student)
    await server.log(Event.LOGIN, username=user.username, ip=client.ip)
    user_info = UserInfo(
        id=user.id, username=user.username, full_name=user.full_name, class_name=class_name
    )
    await client.send(encode(MsgType.LOGIN_OK, LoginOk(user=user_info), envelope.id))

    # Sınav başladıktan sonra giren veya bağlantısı kopup geri gelen öğrenci:
    # exam_start kayıtlı cevaplarıyla birlikte tekrar gönderilir.
    exam_id = await asyncio.to_thread(
        exam_session.find_active_exam_for_student, user.id, server.clock()
    )
    if exam_id is not None:
        await server.send_exam_start(client, exam_id)


async def handle_save_answer(server: WsServer, client: ClientState, envelope: Envelope) -> None:
    request = parse_payload(envelope)
    assert isinstance(request, SaveAnswerRequest) and client.student is not None
    try:
        result = await asyncio.to_thread(
            exam_session.save_answer, client.student.user_id, request, client.ip, server.clock()
        )
    except ExamSessionError as exc:
        await _reject(server, client, envelope, request.exam_id, exc)
        return
    reply = SaveOk(question_id=result.question_id, saved_at=result.saved_at)
    await client.send(encode(MsgType.SAVE_OK, reply, envelope.id))
    server.notify("on_answer_saved", client.student, request.exam_id, result.answered_count)


async def handle_submit(server: WsServer, client: ClientState, envelope: Envelope) -> None:
    request = parse_payload(envelope)
    assert isinstance(request, SubmitRequest) and client.student is not None
    try:
        result = await asyncio.to_thread(
            exam_session.submit, client.student.user_id, request.exam_id, client.ip, server.clock()
        )
    except ExamSessionError as exc:
        await _reject(server, client, envelope, request.exam_id, exc)
        return
    await server.log(
        Event.SUBMITTED, username=client.student.username, exam_id=request.exam_id, ip=client.ip
    )
    await client.send(encode(MsgType.SUBMIT_OK, SubmitOk(submitted_at=result.submitted_at), envelope.id))
    server.notify("on_submitted", client.student.username, request.exam_id, False)
    server.grade_in_background([result.submission_id])


async def handle_focus_lost(server: WsServer, client: ClientState, envelope: Envelope) -> None:
    """Öğrenci sınav penceresinden çıktı. Sadece loglanır, cevap gönderilmez."""
    request = parse_payload(envelope)
    assert isinstance(request, FocusLostRequest) and client.student is not None
    await server.log(
        Event.FOCUS_LOST, username=client.student.username, exam_id=request.exam_id,
        ip=client.ip, detail=f"İstemci saati: {request.at.isoformat()}",
    )
    server.notify("on_focus_lost", client.student, request.exam_id)


async def _reject(
    server: WsServer, client: ClientState, envelope: Envelope, exam_id: int, exc: ExamSessionError
) -> None:
    """İsteği reddeder. Süre dolduktan sonra gelen istekler 'rejected_late' olarak loglanır."""
    if exc.code == ErrorCode.TIME_UP:
        assert client.student is not None
        await server.log(
            Event.REJECTED_LATE, username=client.student.username, exam_id=exam_id,
            ip=client.ip, detail=envelope.type,
        )
    await client.send_error(exc.code, exc.message, envelope.id)


async def handle_ping(server: WsServer, client: ClientState, envelope: Envelope) -> None:
    await client.send(encode(MsgType.PONG, Pong(server_now=server.clock()), envelope.id))


# Mesaj tipi -> handler. Yeni mesaj tipleri buraya eklenir.
HANDLERS: dict[str, Handler] = {
    MsgType.LOGIN: handle_login,
    MsgType.SAVE_ANSWER: handle_save_answer,
    MsgType.SUBMIT: handle_submit,
    MsgType.FOCUS_LOST: handle_focus_lost,
    MsgType.PING: handle_ping,
}

# Giriş yapmadan gönderilebilen mesaj tipleri.
PUBLIC_TYPES: set[str] = {MsgType.LOGIN, MsgType.PING}
