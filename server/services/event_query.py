"""Loglar sekmesi için olay kaydı okuma ve dışa aktarma. (Sahibi: B)

Olayları YAZMAK server/services/event_log.py'nin (A) işidir; bu dosya sadece okur.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select

from server.db.models import EventLog, Exam
from server.db.session import get_session
from server.services.event_log import Event

DEFAULT_LIMIT = 5000  # tablo çok uzarsa arayüz yavaşlamasın

# Arayüzde ve dışa aktarmada gösterilen olay adları
EVENT_LABELS = {
    Event.LOGIN: "Giriş",
    Event.LOGIN_FAILED: "Hatalı giriş",
    Event.EXAM_STARTED: "Sınav başladı",
    Event.EXAM_STOPPED: "Sınav durduruldu",
    Event.EXAM_EXTENDED: "Süre eklendi",
    Event.SUBMITTED: "Gönderdi",
    Event.AUTO_SUBMITTED: "Otomatik gönderildi",
    Event.REJECTED_LATE: "Geç istek reddedildi",
    Event.FOCUS_LOST: "Pencereden çıktı",
    Event.DISCONNECTED: "Bağlantı koptu",
    Event.DUPLICATE_SESSION: "Çift oturum",
}

EXPORT_HEADERS = ["Zaman", "Olay", "Öğrenci", "Sınav", "IP", "Ayrıntı"]


@dataclass
class EventFilter:
    """Boş (None) bırakılan alan filtrelenmez. Tarihler saat dilimli olmalı."""

    exam_id: int | None = None
    username: str | None = None
    event: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass(frozen=True)
class EventRow:
    id: int
    at: datetime          # UTC
    event: str
    username: str | None
    exam_id: int | None
    exam_title: str       # sınav silinmişse veya olay sınavsızsa ""
    ip: str | None
    detail: str | None


def event_label(event: str) -> str:
    return EVENT_LABELS.get(event, event)


def list_events(filters: EventFilter, limit: int = DEFAULT_LIMIT) -> list[EventRow]:
    """Filtreye uyan olaylar, en yeni en üstte, en fazla `limit` tane."""
    query = (
        select(EventLog, Exam.title)
        .outerjoin(Exam, Exam.id == EventLog.exam_id)
        .order_by(EventLog.at.desc(), EventLog.id.desc())
        .limit(limit)
    )
    if filters.exam_id is not None:
        query = query.where(EventLog.exam_id == filters.exam_id)
    if filters.username:
        query = query.where(EventLog.username == filters.username.strip())
    if filters.event:
        query = query.where(EventLog.event == filters.event)
    if filters.date_from is not None:
        query = query.where(EventLog.at >= filters.date_from)
    if filters.date_to is not None:
        query = query.where(EventLog.at <= filters.date_to)

    with get_session() as session:
        return [
            EventRow(
                id=log.id, at=log.at, event=log.event, username=log.username,
                exam_id=log.exam_id, exam_title=title or "", ip=log.ip, detail=log.detail,
            )
            for log, title in session.execute(query)
        ]


def list_event_usernames() -> list[str]:
    """Loglarda geçen kullanıcı adları (öğrenci filtresi için), sıralı."""
    query = (
        select(EventLog.username).where(EventLog.username.is_not(None)).distinct()
        .order_by(EventLog.username)
    )
    with get_session() as session:
        return list(session.scalars(query))


# ---------------------------------------------------------------------------
# Dışa aktarma
# ---------------------------------------------------------------------------

def export_events_csv(rows: list[EventRow], path: Path | str) -> None:
    """CSV olarak kaydeder. UTF-8-BOM ve ';' ayırıcı: Türkçe Excel dosyayı doğru açsın."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(EXPORT_HEADERS)
        writer.writerows(_export_values(row) for row in rows)


def export_events_xlsx(rows: list[EventRow], path: Path | str) -> None:
    """Excel (.xlsx) olarak kaydeder."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Olaylar"
    sheet.append(EXPORT_HEADERS)
    for row in rows:
        sheet.append(_export_values(row))
    for column, width in zip("ABCDEF", (20, 22, 14, 30, 16, 50)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    workbook.save(path)


def _export_values(row: EventRow) -> list[str]:
    local_time = row.at.astimezone()  # UTC → bilgisayarın yerel saati
    return [
        local_time.strftime("%d.%m.%Y %H:%M:%S"),
        event_label(row.event),
        row.username or "",
        row.exam_title or (str(row.exam_id) if row.exam_id else ""),
        row.ip or "",
        row.detail or "",
    ]
