"""Loglar sekmesi için olay kaydı okuma ve dışa aktarma. (Sahibi: B)

Olayları YAZMAK server/services/event_log.py'nin (A) işidir; bu dosya sadece okur.
"""

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select

from server.db.models import EventLog, Exam, User
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

EMPTY_CELL = "—"  # boş hücrede gösterilen işaret

# Ayrıntı metnindeki ISO 8601 zamanlar, ör. "2026-11-06T20:31:33.123456+00:00"
ISO_TIME_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
)


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
    full_name: str        # kullanıcı veri tabanında yoksa ""
    exam_id: int | None
    exam_title: str       # sınav silinmişse veya olay sınavsızsa ""
    ip: str | None
    detail: str | None


def event_label(event: str) -> str:
    return EVENT_LABELS.get(event, event)


def list_events(filters: EventFilter, limit: int = DEFAULT_LIMIT) -> list[EventRow]:
    """Filtreye uyan olaylar, en yeni en üstte, en fazla `limit` tane."""
    query = (
        select(EventLog, Exam.title, User.full_name)
        .outerjoin(Exam, Exam.id == EventLog.exam_id)
        .outerjoin(User, User.username == EventLog.username)
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
                full_name=full_name or "", exam_id=log.exam_id, exam_title=title or "",
                ip=log.ip, detail=log.detail,
            )
            for log, title, full_name in session.execute(query)
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
# Hücre metinleri (Loglar sekmesi ve dışa aktarma aynı metni kullanır)
# ---------------------------------------------------------------------------

def user_text(row: EventRow) -> str:
    """Öğrenci no + ad soyad, ör. "260101002 · Ece Özdemir"."""
    if not row.username:
        return ""
    if not row.full_name:
        return row.username
    return f"{row.username} · {row.full_name}"


def exam_text(row: EventRow) -> str:
    return row.exam_title or (str(row.exam_id) if row.exam_id else "")


def ip_text(ip: str | None) -> str:
    return ip or EMPTY_CELL


def format_detail(detail: str | None) -> str:
    """Ayrıntıdaki ISO/UTC zamanları yerel saate çevirir: "Bitiş: 2026-...T20:31:33+00:00" → "Bitiş: 23:31:33"."""
    if not detail:
        return ""
    return ISO_TIME_PATTERN.sub(_local_time_text, detail)


def _local_time_text(match: re.Match[str]) -> str:
    text = match.group(0)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return text  # tanınmayan zaman olduğu gibi kalsın
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)  # veri tabanındaki zamanlar UTC
    return moment.astimezone().strftime("%H:%M:%S")


def time_text(row: EventRow) -> str:
    return row.at.astimezone().strftime("%d.%m.%Y %H:%M:%S")  # UTC → bilgisayarın yerel saati


# ---------------------------------------------------------------------------
# Dışa aktarma
# ---------------------------------------------------------------------------

def export_events_csv(rows: list[EventRow], path: Path | str) -> None:
    """CSV olarak kaydeder. UTF-8-BOM ve ';' ayırıcı: Türkçe Excel dosyayı doğru açsın."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(EXPORT_HEADERS)
        writer.writerows(row_values(row) for row in rows)


def export_events_xlsx(rows: list[EventRow], path: Path | str) -> None:
    """Excel (.xlsx) olarak kaydeder."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Olaylar"
    sheet.append(EXPORT_HEADERS)
    for row in rows:
        sheet.append(row_values(row))
    for column, width in zip("ABCDEF", (20, 22, 30, 30, 16, 50)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    workbook.save(path)


def row_values(row: EventRow) -> list[str]:
    """Bir olayın sütun metinleri, EXPORT_HEADERS sırasıyla."""
    return [
        time_text(row),
        event_label(row.event),
        user_text(row),
        exam_text(row),
        ip_text(row.ip),
        format_detail(row.detail),
    ]
