import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from server.db.models import EventLog
from server.db.session import get_session
from server.services.event_log import Event, log_event


def test_log_event_writes_file_and_table(empty_db, temp_events_log: Path) -> None:
    at = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
    log_event(Event.FOCUS_LOST, username="260101001", exam_id=3, ip="10.0.0.5", detail="Öğrenci çıktı", at=at)
    log_event(Event.LOGIN, username="260101002")

    lines = temp_events_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {
        "at": "2026-11-05T10:00:00+00:00", "event": "focus_lost", "username": "260101001",
        "exam_id": 3, "ip": "10.0.0.5", "detail": "Öğrenci çıktı",
    }

    with get_session() as session:
        rows = session.scalars(select(EventLog).order_by(EventLog.id)).all()
    assert [r.event for r in rows] == ["focus_lost", "login"]
    assert rows[0].at == at and rows[0].detail == "Öğrenci çıktı"


def test_log_event_does_not_raise_without_db_table(empty_db, temp_events_log: Path) -> None:
    """Veri tabanına yazılamazsa bile istek bozulmamalı; dosyaya yine yazılır."""
    from server.db.session import get_engine

    EventLog.__table__.drop(get_engine())
    log_event(Event.LOGIN, username="260101001")  # hata fırlatmamalı
    assert "260101001" in temp_events_log.read_text(encoding="utf-8")
