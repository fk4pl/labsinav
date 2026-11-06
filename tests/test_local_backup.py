"""Öğrenci bilgisayarındaki yerel yedek dosyası."""

from datetime import datetime, timezone
from pathlib import Path

from shared.protocol import SavedAnswer
from student_app.local_backup import LocalBackup, default_backup_dir

AT = datetime(2026, 11, 7, 9, 30, tzinfo=timezone.utc)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    backup = LocalBackup(tmp_path / "backups", "260101001", 3)
    answers = {
        10: SavedAnswer(selected_option_id=100, updated_at=AT),
        20: SavedAnswer(text_answer="Türkçe İı ğüşöç", updated_at=AT),
    }
    backup.save(answers, {20})
    assert backup.path.name == "260101001_3.json"
    assert not backup.path.with_suffix(".json.tmp").exists()  # geçici dosya kalmaz

    data = LocalBackup(tmp_path / "backups", "260101001", 3).load()
    assert data is not None
    assert data.answers == answers
    assert data.marked == {20}


def test_load_missing_or_corrupt_returns_none(tmp_path: Path) -> None:
    backup = LocalBackup(tmp_path, "260101001", 3)
    assert backup.load() is None
    backup.path.write_text("{bozuk", encoding="utf-8")
    assert backup.load() is None


def test_backup_of_other_student_is_not_used(tmp_path: Path) -> None:
    LocalBackup(tmp_path, "260101001", 3).save({10: SavedAnswer(text_answer="a", updated_at=AT)}, set())
    other = LocalBackup(tmp_path, "260101001", 3)
    other.username = "260101002"  # dosya adı aynı kalsa bile içerik kontrol edilir
    assert other.load() is None


def test_answers_without_time_are_ignored(tmp_path: Path) -> None:
    backup = LocalBackup(tmp_path, "260101001", 3)
    backup.save({10: SavedAnswer(text_answer="zamansız")}, set())
    data = backup.load()
    assert data is not None and data.answers == {}


def test_delete(tmp_path: Path) -> None:
    backup = LocalBackup(tmp_path, "260101001", 3)
    backup.save({}, set())
    backup.delete()
    assert not backup.path.exists()
    backup.delete()  # dosya yoksa da hata vermez


def test_default_dir_is_user_data_folder() -> None:
    path = default_backup_dir()
    assert path.name == "backups" and "LabSinav" in str(path)
