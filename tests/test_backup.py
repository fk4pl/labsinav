"""Veri tabanı yedeği: tarihli ad, WAL'deki son yazmalar dahil tam kopya."""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from server.db.models import User
from server.db.session import write_session
from server.services.backup import backup_database, current_db_path, default_backup_name


def test_default_backup_name_has_date_and_time() -> None:
    assert default_backup_name(datetime(2026, 11, 10, 14, 30)) == "labsinav_yedek_2026-11-10_14-30.db"


def test_backup_copies_all_data(seeded_db: Path, tmp_path: Path) -> None:
    # Yeni bir yazma: WAL dosyasında bekler; yedekte de görünmeli.
    with write_session() as session:
        session.scalars(select(User).where(User.username == "egitmen")).one().full_name = "Yeni Ad"
    assert current_db_path() == seeded_db

    target = backup_database(tmp_path / "yedekler" / "yedek.db")

    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 31
        name = connection.execute("SELECT full_name FROM users WHERE username='egitmen'").fetchone()[0]
    assert name == "Yeni Ad"


def test_backup_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "yedek.db", source=tmp_path / "yok.db")
