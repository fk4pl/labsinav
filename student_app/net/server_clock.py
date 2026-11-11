"""Sunucu saatinin istemcideki tahmini. (Sahibi: C)

Süreyi sunucu belirler. Öğrencinin bilgisayar saati yanlış olabilir
ya da sınav sırasında değiştirilebilir. Bu yüzden:
  - sunucudan her server_now geldiğinde (exam_start, exam_update, pong) onu ve o anın
    monotonic zamanını kaydederiz,
  - "şu an sunucuda saat kaç?" sorusunu: son_server_now + (geçen monotonic süre) ile cevaplarız.
time.monotonic() bilgisayar saati değiştirilse de geri gitmez/zıplamaz.
"""

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone


class ServerClock:
    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        # Testlerde sahte bir monotonic fonksiyonu verilebilir.
        self._monotonic = monotonic
        self._server_time: datetime | None = None
        self._mono_at_update = 0.0

    def update(self, server_now: datetime) -> None:
        """Sunucudan gelen saati kaydeder."""
        if server_now.tzinfo is None:
            server_now = server_now.replace(tzinfo=timezone.utc)
        self._server_time = server_now
        self._mono_at_update = self._monotonic()

    def now(self) -> datetime:
        """Sunucudaki şu anki saatin tahmini (UTC). Henüz bilgi yoksa yerel saat kullanılır."""
        if self._server_time is None:
            return datetime.now(timezone.utc)
        elapsed = self._monotonic() - self._mono_at_update
        return self._server_time + timedelta(seconds=elapsed)

    def seconds_until(self, moment: datetime) -> float:
        """moment'a kaç saniye kaldı (geçtiyse negatif)."""
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return (moment - self.now()).total_seconds()
