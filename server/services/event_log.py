"""Olay kaydı: logs/events.log (JSON Lines) + event_logs tablosu. (Sahibi: A)

Her olay iki yere yazılır:
1. logs/events.log — her satır bir JSON nesnesi. Uygulama çökse bile elde kalır.
2. event_logs tablosu — eğitmen arayüzündeki "Loglar" sekmesi buradan filtreleyerek okur.

Kullanım:
    log_event(Event.LOGIN, username="260101001", ip="192.168.1.20")

Log yazılamazsa (disk dolu vb.) hata sadece Python loguna yazılır; öğrencinin isteği
bu yüzden BAŞARISIZ OLMAZ.
"""

import json
import logging
import threading
from datetime import datetime

from server.db.models import EventLog, utcnow
from server.db.session import write_session
from shared import config

logger = logging.getLogger(__name__)

_file_lock = threading.Lock()  # iki thread aynı anda yazarsa satırlar birbirine karışmasın


class Event:
    """Olay adları. Kodda string yazmak yerine bu sabitleri kullan."""

    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    EXAM_STARTED = "exam_started"
    EXAM_STOPPED = "exam_stopped"
    EXAM_EXTENDED = "exam_extended"
    SUBMITTED = "submitted"
    AUTO_SUBMITTED = "auto_submitted"
    REJECTED_LATE = "rejected_late"
    FOCUS_LOST = "focus_lost"
    DISCONNECTED = "disconnected"
    DUPLICATE_SESSION = "duplicate_session"


def log_event(
    event: str,
    username: str | None = None,
    exam_id: int | None = None,
    ip: str | None = None,
    detail: str | None = None,
    at: datetime | None = None,
) -> None:
    """Olayı dosyaya ve veri tabanına yazar."""
    at = at or utcnow()
    _write_to_file(event, username, exam_id, ip, detail, at)
    _write_to_db(event, username, exam_id, ip, detail, at)


def _write_to_file(
    event: str, username: str | None, exam_id: int | None,
    ip: str | None, detail: str | None, at: datetime,
) -> None:
    record = {
        "at": at.isoformat(), "event": event, "username": username,
        "exam_id": exam_id, "ip": ip, "detail": detail,
    }
    line = json.dumps(record, ensure_ascii=False)
    try:
        path = config.EVENTS_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with _file_lock, open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        logger.exception("Olay dosyaya yazılamadı: %s", line)


def _write_to_db(
    event: str, username: str | None, exam_id: int | None,
    ip: str | None, detail: str | None, at: datetime,
) -> None:
    try:
        with write_session() as session:
            session.add(EventLog(
                at=at, event=event, username=username, exam_id=exam_id, ip=ip, detail=detail,
            ))
    except Exception:
        logger.exception("Olay veri tabanına yazılamadı: %s %s", event, username)
