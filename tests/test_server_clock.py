from datetime import datetime, timedelta, timezone

from student_app.net.server_clock import ServerClock

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def test_now_follows_server_time_not_local_clock() -> None:
    mono = FakeMonotonic()
    clock = ServerClock(mono)
    clock.update(T0)
    mono.value += 90
    assert clock.now() == T0 + timedelta(seconds=90)


def test_seconds_until_uses_latest_update() -> None:
    mono = FakeMonotonic()
    clock = ServerClock(mono)
    clock.update(T0)
    ends_at = T0 + timedelta(minutes=10)
    mono.value += 60
    assert clock.seconds_until(ends_at) == 540
    clock.update(T0 + timedelta(seconds=65))  # pong: sunucu 5 sn ileride çıktı
    assert clock.seconds_until(ends_at) == 535


def test_naive_datetime_is_treated_as_utc() -> None:
    clock = ServerClock(FakeMonotonic())
    clock.update(T0.replace(tzinfo=None))
    assert clock.now() == T0


def test_without_update_falls_back_to_local_time() -> None:
    clock = ServerClock()
    assert abs((clock.now() - datetime.now(timezone.utc)).total_seconds()) < 1
