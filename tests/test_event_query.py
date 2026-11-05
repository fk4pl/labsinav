"""event_query servis testleri: log filtreleme ve CSV/Excel aktarma."""

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
