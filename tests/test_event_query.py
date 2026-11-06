"""event_query servis testleri: log filtreleme ve CSV/Excel aktarma."""

import csv
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from openpyxl import load_workbook

from server.services import event_query
from server.services.event_log import Event, log_event
from server.services.event_query import EventFilter

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


def add_sample_events() -> None:
    log_event(Event.LOGIN, username="260101001", ip="10.0.0.1", at=T0)
    log_event(Event.FOCUS_LOST, username="260101001", exam_id=1, at=T0 + timedelta(minutes=5))
    log_event(Event.LOGIN_FAILED, username="260101002", detail="Hatalı şifre", at=T0 + timedelta(minutes=10))
    log_event(Event.EXAM_STARTED, exam_id=2, at=T0 + timedelta(minutes=15))


def test_list_events_newest_first(empty_db) -> None:
    add_sample_events()
    rows = event_query.list_events(EventFilter())
    assert [r.event for r in rows] == [
        Event.EXAM_STARTED, Event.LOGIN_FAILED, Event.FOCUS_LOST, Event.LOGIN,
    ]


def test_list_events_filters(empty_db) -> None:
    add_sample_events()
    assert len(event_query.list_events(EventFilter(username="260101001"))) == 2
    assert len(event_query.list_events(EventFilter(event=Event.LOGIN_FAILED))) == 1
    assert len(event_query.list_events(EventFilter(exam_id=1))) == 1
    between = EventFilter(date_from=T0 + timedelta(minutes=4), date_to=T0 + timedelta(minutes=11))
    assert [r.event for r in event_query.list_events(between)] == [Event.LOGIN_FAILED, Event.FOCUS_LOST]


def test_list_events_limit(empty_db) -> None:
    add_sample_events()
    assert len(event_query.list_events(EventFilter(), limit=2)) == 2


def test_list_event_usernames(empty_db) -> None:
    add_sample_events()
    assert event_query.list_event_usernames() == ["260101001", "260101002"]


def test_export_csv(empty_db, tmp_path: Path) -> None:
    add_sample_events()
    path = tmp_path / "olaylar.csv"
    event_query.export_events_csv(event_query.list_events(EventFilter()), path)

    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = list(csv.reader(f, delimiter=";"))
    assert lines[0] == event_query.EXPORT_HEADERS
    assert len(lines) == 5
    assert lines[2][1] == "Hatalı giriş"
    assert lines[2][5] == "Hatalı şifre"


def test_export_xlsx(empty_db, tmp_path: Path) -> None:
    add_sample_events()
    path = tmp_path / "olaylar.xlsx"
    event_query.export_events_xlsx(event_query.list_events(EventFilter()), path)

    sheet = load_workbook(path).active
    values = list(sheet.iter_rows(values_only=True))
    assert list(values[0]) == event_query.EXPORT_HEADERS
    assert len(values) == 5
    assert values[3][1] == "Pencereden çıktı"


# --- Hücre metinleri: yerel saat, "no · ad soyad", boş IP ---

@pytest.fixture
def istanbul_time(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Yerel saati sabitle (UTC+3) ki sonuç test eden bilgisayara bağlı olmasın."""
    monkeypatch.setenv("TZ", "Europe/Istanbul")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_format_detail_converts_iso_times_to_local(istanbul_time) -> None:
    assert event_query.format_detail("Bitiş: 2026-11-06T20:31:33.123456+00:00") == "Bitiş: 23:31:33"
    assert event_query.format_detail("+5 dk, yeni bitiş: 2026-11-06T20:36:33+00:00") == (
        "+5 dk, yeni bitiş: 23:36:33"
    )
    # Saat dilimi yazmayan zaman UTC kabul edilir
    assert event_query.format_detail("İstemci saati: 2026-11-06T20:31:33") == "İstemci saati: 23:31:33"


def test_format_detail_leaves_other_text(istanbul_time) -> None:
    assert event_query.format_detail(None) == ""
    assert event_query.format_detail("Hatalı şifre") == "Hatalı şifre"
    assert event_query.format_detail("Saat: 2026-13-45T99:99:99") == "Saat: 2026-13-45T99:99:99"


def test_row_values_show_full_name_and_dash_for_empty_ip(seeded_db, istanbul_time) -> None:
    log_event(Event.FOCUS_LOST, username="260101002", detail="İstemci saati: 2026-11-05T10:05:00+00:00", at=T0)
    log_event(Event.LOGIN_FAILED, username="bilinmeyen", ip="10.0.0.9", at=T0 + timedelta(minutes=1))
    unknown, focus = event_query.list_events(EventFilter())

    values = event_query.row_values(focus)
    assert values[0] == "05.11.2026 13:00:00"
    assert values[2] == f"260101002 · {focus.full_name}" and focus.full_name
    assert values[4] == "—"
    assert values[5] == "İstemci saati: 13:05:00"
    assert event_query.row_values(unknown)[2] == "bilinmeyen"  # veri tabanında yok: sadece numara
    assert event_query.row_values(unknown)[4] == "10.0.0.9"


def test_export_uses_display_texts(seeded_db, istanbul_time, tmp_path: Path) -> None:
    log_event(Event.EXAM_STARTED, username="260101002", detail="Bitiş: 2026-11-05T11:00:00+00:00", at=T0)
    rows = event_query.list_events(EventFilter())
    csv_path, xlsx_path = tmp_path / "o.csv", tmp_path / "o.xlsx"
    event_query.export_events_csv(rows, csv_path)
    event_query.export_events_xlsx(rows, xlsx_path)

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        csv_row = list(csv.reader(f, delimiter=";"))[1]
    xlsx_row = list(load_workbook(xlsx_path).active.iter_rows(values_only=True))[1]
    for row in (csv_row, list(xlsx_row)):
        assert row[2].startswith("260101002 · ")
        assert row[4] == "—"
        assert row[5] == "Bitiş: 14:00:00"
