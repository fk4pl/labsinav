"""init_db(): eski veri tabanı dosyasında eksik sütunları ekler."""

from pathlib import Path

from sqlalchemy import inspect, text

from server.db import session as db_session


def test_init_db_adds_missing_is_manual_column(tmp_path: Path) -> None:
    db_session.configure(tmp_path / "old.db")
    engine = db_session.get_engine()
    db_session.init_db()
    # Eski sürümü taklit et: is_manual sütunu olmayan veri tabanı
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE answers DROP COLUMN is_manual"))
    assert "is_manual" not in {c["name"] for c in inspect(engine).get_columns("answers")}

    db_session.init_db()
    db_session.init_db()  # ikinci kez çağırmak hata vermemeli

    assert "is_manual" in {c["name"] for c in inspect(engine).get_columns("answers")}
    engine.dispose()
