"""Sahte öğrencilerle yük testi: python -m scripts.fake_students -n 40

Ne yapar?
- N öğrenci (seed'deki 260101001, 260101002, …; şifre = öğrenci no) AYNI ANDA bağlanır ve giriş yapar.
- Sunucu adresi verilmezse (--host) UDP keşfiyle bulunur (öğrenci uygulamasının yaptığı gibi).
- Eğitmen sınavı başlatana kadar bekler; sonra rastgele aralıklarla rastgele cevap kaydeder
  (mcq'de rastgele şık, klasikte küçük bir listeden metin).
- Öğrencilerin bir kısmı erken gönderir, bir kısmı bağlantıyı koparıp tekrar bağlanır
  (sunucunun kayıtlı cevapları geri yollayıp yollamadığı kontrol edilir), bir kısmı
  focus_lost gönderir; kalanlar sürenin dolmasını (exam_end) bekler.
- Sonunda özet yazar: bağlanan, gönderen, otomatik gönderilen, hata alan, save_answer cevap süreleri.

Kullanım (önce eğitmen uygulaması açık ve giriş yapılmış olmalı):
    python -m scripts.seed --students 80          # A sınıfında 40 öğrenci
    python -m scripts.fake_students -n 40          # sonra eğitmen arayüzünden sınavı başlatın

Bu betik Qt kullanmaz; tüm öğrenciler tek bir asyncio döngüsünde çalışır.
"""

import argparse
import asyncio
import contextlib
import json
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from server.net.discovery import discover_server
from shared import config

FIRST_STUDENT_NO = 260101001
CLASSIC_ANSWER_POOL = ["0", "sıfır", "strlen", "null", "&", "*", "default", "3", "bilmiyorum", "  STDLIB.H "]

# Süre dolarken yola çıkmış istekler TIME_UP alabilir; bunlar hata sayılmaz.
EXPECTED_ERROR_CODES = {"TIME_UP"}


@dataclass
class Options:
    count: int = 30
    first: int = FIRST_STUDENT_NO
    host: str | None = None
    port: int = config.WS_PORT
    min_delay: float = 1.0          # iki kayıt arası en az (sn)
    max_delay: float = 5.0          # iki kayıt arası en fazla (sn)
    early_ratio: float = 0.2        # erken gönderenlerin oranı
    reconnect_ratio: float = 0.2    # bağlantıyı koparıp tekrar bağlananların oranı
    focus_ratio: float = 0.3        # pencereden çıkanların (focus_lost) oranı
    wait_start: float = 600.0       # sınavın başlamasını en fazla bu kadar bekle (sn)
    seed: int | None = None         # aynı sayı → aynı rastgele davranış
    quiet: bool = False             # öğrenci başına satır yazma


@dataclass
class Stats:
    """Tüm sahte öğrencilerin ortak sayaçları (tek asyncio döngüsü → kilit gerekmez)."""

    connected: set[str] = field(default_factory=set)   # en az bir kez bağlanabilenler
    connected_now: int = 0
    peak_connected: int = 0                            # aynı anda bağlı en yüksek sayı
    logged_in: int = 0
    exam_started: int = 0
    submitted: int = 0
    auto_submitted: int = 0
    reconnects: int = 0
    reconnect_ok: int = 0
    focus_lost: int = 0
    saves: int = 0
    save_latencies_ms: list[float] = field(default_factory=list)
    login_latencies_ms: list[float] = field(default_factory=list)
    errors: Counter = field(default_factory=Counter)           # error.code → adet
    expected_errors: Counter = field(default_factory=Counter)  # ör. süre dolarken TIME_UP
    failed_students: set[str] = field(default_factory=set)     # beklenmeyen hata alanlar

    def on_connected(self, username: str) -> None:
        self.connected.add(username)
        self.connected_now += 1
        self.peak_connected = max(self.peak_connected, self.connected_now)

    def fail(self, username: str, reason: str) -> None:
        self.errors[reason] += 1
        self.failed_students.add(username)


@dataclass
class Role:
    early_submit: bool
    reconnect: bool
    focus_lost: bool


def assign_roles(count: int, options: Options, rng: random.Random) -> list[Role]:
    """Rolleri oranlara göre dağıtır. Erken gönderen, bağlantı koparan ve kalanlar ayrı gruplardır."""
    early = round(count * options.early_ratio)
    reconnect = round(count * options.reconnect_ratio)
    kinds = ["early"] * early + ["reconnect"] * reconnect
    kinds += ["wait"] * max(0, count - len(kinds))
    rng.shuffle(kinds)
    return [
        Role(early_submit=k == "early", reconnect=k == "reconnect", focus_lost=rng.random() < options.focus_ratio)
        for k in kinds[:count]
    ]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeStudent:
    """Tek bir sahte öğrenci. run() bitince öğrencinin işi bitmiştir."""

    def __init__(self, username: str, role: Role, url: str, options: Options,
                 stats: Stats, rng: random.Random) -> None:
        self.username = username
        self.role = role
        self.url = url
        self.options = options
        self.stats = stats
        self.rng = rng
        self.ws: ClientConnection | None = None
        self.exam: dict | None = None
        self.saved: dict[int, Any] = {}               # question_id → sunucunun onayladığı değer
        self.server_saved: dict[int, dict] | None = None  # son exam_start'taki saved_answers
        self.pending: dict[str, tuple[str, float, Any]] = {}  # id → (tip, gönderim anı, ek bilgi)
        self.submitted = False
        self.exam_over = asyncio.Event()
        self.exam_started = asyncio.Event()
        self.login_done: asyncio.Future | None = None
        self.submit_done = asyncio.Event()
        self._counter = 0
        self._reader: asyncio.Task | None = None
        self._closing = False   # bağlantıyı biz mi kapattık?

    # --- Ana akış ---

    async def run(self) -> None:
        try:
            if not await self._connect_and_login():
                return
            if not await self._wait_for_exam():
                return
            await self._take_exam()
            await self.exam_over.wait()
            if not self.submitted:
                self.stats.auto_submitted += 1
        except (OSError, ConnectionClosed, TimeoutError) as exc:
            self.stats.fail(self.username, f"bağlantı: {type(exc).__name__}")
        finally:
            await self._close()

    async def _connect_and_login(self) -> bool:
        try:
            self.ws = await connect(self.url, open_timeout=10, max_size=config.MAX_MESSAGE_BYTES)
        except (OSError, TimeoutError) as exc:
            self.stats.fail(self.username, f"bağlanamadı: {type(exc).__name__}")
            return False
        self.stats.on_connected(self.username)
        self._closing = False
        self._reader = asyncio.create_task(self._read_loop(self.ws))
        self.login_done = asyncio.get_running_loop().create_future()
        started = time.perf_counter()
        await self._send("login", {"username": self.username, "password": self.username})
        ok = await asyncio.wait_for(self.login_done, timeout=30)
        if ok:
            self.stats.login_latencies_ms.append((time.perf_counter() - started) * 1000)
        return ok

    async def _wait_for_exam(self) -> bool:
        try:
            await asyncio.wait_for(self.exam_started.wait(), timeout=self.options.wait_start)
            return True
        except TimeoutError:
            self.stats.fail(self.username, "sınav başlamadı (bekleme süresi doldu)")
            return False

    async def _take_exam(self) -> None:
        """Sınav bitene, öğrenci gönderene kadar cevap kaydeder; role göre ara işler yapar."""
        submit_after = self.rng.randint(3, 8) if self.role.early_submit else None
        reconnect_after = self.rng.randint(2, 5) if self.role.reconnect else None
        focus_after = self.rng.randint(1, 4) if self.role.focus_lost else None
        step = 0
        while not self.exam_over.is_set():
            if not await self._sleep(self.rng.uniform(self.options.min_delay, self.options.max_delay)):
                return  # sınav bitti
            step += 1
            await self._save_random_answer()
            if step == focus_after:
                await self._send_focus_lost()
            if step == reconnect_after:
                await self._reconnect()
            if step == submit_after:
                await self._submit()
                return

    # --- Eylemler ---

    async def _save_random_answer(self) -> None:
        question = self.rng.choice(self.exam["questions"])
        payload: dict[str, Any] = {"exam_id": self.exam["id"], "question_id": question["id"]}
        if question["type"] == "mcq" and question["options"]:
            value = self.rng.choice(question["options"])["id"]
            payload["selected_option_id"] = value
        elif question["type"] == "code":
            value = "int main(void) { return 0; }\n"
            payload["code"] = value
        else:
            value = self.rng.choice(CLASSIC_ANSWER_POOL)
            payload["text_answer"] = value
        await self._send("save_answer", payload, extra=(question["id"], value))

    async def _send_focus_lost(self) -> None:
        await self._send("focus_lost", {"exam_id": self.exam["id"], "at": now_iso()}, expect_reply=False)
        self.stats.focus_lost += 1

    async def _submit(self) -> None:
        await self._wait_pending()
        await self._send("submit", {"exam_id": self.exam["id"]})
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.submit_done.wait(), timeout=30)

    async def _reconnect(self) -> None:
        """Bağlantıyı koparır, biraz bekleyip yeniden girer; kayıtlı cevaplar geri geldi mi bakar."""
        await self._wait_pending()
        self.stats.reconnects += 1
        await self._close()
        await asyncio.sleep(self.rng.uniform(self.options.min_delay, self.options.max_delay))
        self.exam_started.clear()
        if not await self._connect_and_login():
            return
        try:
            # Sınav devam ediyorsa exam_start girişten hemen sonra gelir.
            await asyncio.wait_for(self.exam_started.wait(), timeout=10)
        except TimeoutError:
            self.exam_over.set()  # biz yokken sınav bitmiş (otomatik gönderildi)
            return
        self._check_saved_answers()

    def _check_saved_answers(self) -> None:
        server = self.server_saved or {}
        for question_id, value in self.saved.items():
            answer = server.get(question_id) or {}
            if value not in (answer.get("selected_option_id"), answer.get("text_answer"), answer.get("code")):
                self.stats.fail(self.username, "yeniden bağlanınca kayıtlı cevap eksik/yanlış")
                return
        self.stats.reconnect_ok += 1

    # --- Gönderme / alma ---

    async def _send(self, msg_type: str, payload: dict, extra: Any = None, expect_reply: bool = True) -> None:
        self._counter += 1
        msg_id = f"{self.username}-{self._counter}"
        if expect_reply:
            self.pending[msg_id] = (msg_type, time.perf_counter(), extra)
        assert self.ws is not None
        await self.ws.send(json.dumps({"type": msg_type, "id": msg_id, "payload": payload}))

    async def _read_loop(self, ws: ClientConnection) -> None:
        try:
            async for raw in ws:
                self._handle(json.loads(raw))
        except ConnectionClosed:
            pass
        finally:
            if not self._closing and not self.exam_over.is_set():
                self.stats.fail(self.username, "bağlantı beklenmedik şekilde koptu")
                self.exam_over.set()  # run() takılı kalmasın
            if self.login_done is not None and not self.login_done.done():
                self.login_done.set_result(False)

    def _handle(self, message: dict) -> None:
        msg_type, payload = message.get("type"), message.get("payload") or {}
        request = self.pending.pop(message.get("id"), None)
        if msg_type == "login_ok":
            self.stats.logged_in += 1
            self.login_done.set_result(True)
        elif msg_type == "exam_start":
            self._on_exam_start(payload)
        elif msg_type == "save_ok" and request is not None:
            self._on_save_ok(request)
        elif msg_type == "submit_ok":
            self.submitted = True
            self.stats.submitted += 1
            self.submit_done.set()
        elif msg_type == "exam_end":
            self.exam_over.set()
        elif msg_type == "error":
            self._on_error(payload, request)

    def _on_exam_start(self, payload: dict) -> None:
        if self.exam is None:
            self.stats.exam_started += 1
        self.exam = payload["exam"]
        self.server_saved = {int(k): v for k, v in payload.get("saved_answers", {}).items()}
        self.exam_started.set()

    def _on_save_ok(self, request: tuple[str, float, Any]) -> None:
        _, sent_at, (question_id, value) = request
        self.stats.saves += 1
        self.stats.save_latencies_ms.append((time.perf_counter() - sent_at) * 1000)
        self.saved[question_id] = value

    def _on_error(self, payload: dict, request: tuple[str, float, Any] | None) -> None:
        code = payload.get("code", "?")
        request_type = request[0] if request else "?"
        if code in EXPECTED_ERROR_CODES:
            self.stats.expected_errors[f"{request_type}: {code}"] += 1
        else:
            self.stats.fail(self.username, f"{request_type}: {code}")
        if request_type == "login" and self.login_done is not None and not self.login_done.done():
            self.login_done.set_result(False)
        if request_type == "submit":
            self.submit_done.set()

    # --- Yardımcılar ---

    async def _sleep(self, seconds: float) -> bool:
        """Bekler; sınav bu sırada biterse hemen False döner."""
        try:
            await asyncio.wait_for(self.exam_over.wait(), timeout=seconds)
            return False
        except TimeoutError:
            return True

    async def _wait_pending(self, timeout: float = 10) -> None:
        """Cevabı beklenen isteklerin (ör. son kayıt) cevabı gelene kadar bekler."""
        deadline = time.monotonic() + timeout
        while self.pending and time.monotonic() < deadline:
            await asyncio.sleep(0.02)

    async def _close(self) -> None:
        self._closing = True
        if self.ws is not None:
            self.stats.connected_now -= 1
            await self.ws.close()
        if self._reader is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        self.ws, self._reader = None, None


async def _ping_loop(students: list[FakeStudent]) -> None:
    """Gerçek istemci gibi 10 sn'de bir ping (bağlı olan herkes için)."""
    while True:
        await asyncio.sleep(config.PING_INTERVAL_SEC)
        for student in students:
            if student.ws is not None:
                with contextlib.suppress(ConnectionClosed):
                    await student._send("ping", {}, expect_reply=False)


async def find_server(options: Options) -> tuple[str, int] | None:
    if options.host:
        return options.host, options.port
    print("Sunucu ağda aranıyor (UDP keşif)…")
    return await asyncio.to_thread(discover_server)


async def run(options: Options, url: str, stats: Stats | None = None) -> Stats:
    """Tüm sahte öğrencileri aynı anda çalıştırır ve sayaçları döner."""
    rng = random.Random(options.seed)
    stats = stats if stats is not None else Stats()
    roles = assign_roles(options.count, options, rng)
    students = [
        FakeStudent(str(options.first + i), role, url, options, stats, random.Random(rng.random()))
        for i, role in enumerate(roles)
    ]
    pinger = asyncio.create_task(_ping_loop(students))
    try:
        await asyncio.gather(*(s.run() for s in students))
    finally:
        pinger.cancel()
    return stats


def format_summary(stats: Stats, count: int) -> str:
    lines = [
        "",
        "=" * 52,
        "YÜK TESTİ ÖZETİ",
        "=" * 52,
        f"Öğrenci sayısı                 : {count}",
        f"Bağlanan                       : {len(stats.connected)}",
        f"Aynı anda bağlı (en çok)       : {stats.peak_connected}",
        f"Giriş (yeniden girişler dahil) : {stats.logged_in}",
        f"Sınava giren                   : {stats.exam_started}",
        f"Kendisi gönderen               : {stats.submitted}",
        f"Otomatik gönderilen            : {stats.auto_submitted}",
        f"Yeniden bağlanan / doğrulanan  : {stats.reconnects} / {stats.reconnect_ok}",
        f"focus_lost gönderen            : {stats.focus_lost}",
        f"Kaydedilen cevap (save_ok)     : {stats.saves}",
    ]
    lines += _latency_lines("save_answer", stats.save_latencies_ms)
    lines += _latency_lines("login", stats.login_latencies_ms)
    lines.append(f"Hata alan öğrenci              : {len(stats.failed_students)}")
    for reason, n in stats.errors.most_common():
        lines.append(f"    {reason}: {n}")
    for reason, n in stats.expected_errors.most_common():
        lines.append(f"    (beklenen, hata sayılmaz) {reason}: {n}")
    lines.append("=" * 52)
    return "\n".join(lines)


def _latency_lines(name: str, values: list[float]) -> list[str]:
    if not values:
        return [f"{name} cevap süresi             : ölçüm yok"]
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return [
        f"{name} ort. / p95 / en yavaş : "
        f"{statistics.fmean(values):.1f} / {p95:.1f} / {ordered[-1]:.1f} ms"
    ]


def parse_args(argv: list[str] | None = None) -> Options:
    parser = argparse.ArgumentParser(description="Sahte öğrencilerle LabSınav yük testi.")
    parser.add_argument("-n", "--count", type=int, default=30, help="öğrenci sayısı (varsayılan 30)")
    parser.add_argument("--first", type=int, default=FIRST_STUDENT_NO, help="ilk öğrenci no")
    parser.add_argument("--host", help="sunucu IP'si (verilmezse ağda aranır)")
    parser.add_argument("--port", type=int, default=config.WS_PORT)
    parser.add_argument("--min-delay", type=float, default=1.0, help="kayıtlar arası en az sn")
    parser.add_argument("--max-delay", type=float, default=5.0, help="kayıtlar arası en çok sn")
    parser.add_argument("--early", type=float, default=0.2, help="erken gönderen oranı (0-1)")
    parser.add_argument("--reconnect", type=float, default=0.2, help="bağlantı koparan oranı (0-1)")
    parser.add_argument("--focus", type=float, default=0.3, help="focus_lost gönderen oranı (0-1)")
    parser.add_argument("--wait-start", type=float, default=600, help="sınavın başlaması için bekleme (sn)")
    parser.add_argument("--seed", type=int, help="rastgelelik tohumu (aynı sayı → aynı davranış)")
    args = parser.parse_args(argv)
    if args.count < 1 or not 0 < args.min_delay <= args.max_delay:
        parser.error("-n en az 1 olmalı; 0 < --min-delay <= --max-delay olmalı.")
    if args.early + args.reconnect > 1:
        parser.error("--early + --reconnect en fazla 1 olabilir.")
    return Options(
        count=args.count, first=args.first, host=args.host, port=args.port,
        min_delay=args.min_delay, max_delay=args.max_delay, early_ratio=args.early,
        reconnect_ratio=args.reconnect, focus_ratio=args.focus, wait_start=args.wait_start,
        seed=args.seed,
    )


async def _main(options: Options) -> int:
    address = await find_server(options)
    if address is None:
        print("Sunucu bulunamadı. Eğitmen uygulaması açık mı? --host ile IP verin.")
        return 1
    host, port = address
    print(f"Sunucu: {host}:{port} — {options.count} öğrenci bağlanıyor…")
    print("Eğitmen arayüzünden sınavı başlatın; öğrenciler sınav bitene kadar çalışır (Ctrl+C: dur).")
    stats = Stats()
    try:
        await run(options, f"ws://{host}:{port}", stats)
    finally:
        print(format_summary(stats, options.count))
    return 0 if not stats.failed_students else 2


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    try:
        return asyncio.run(_main(options))
    except KeyboardInterrupt:
        print("\nDurduruldu.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
