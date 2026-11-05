"""Ortak test hazırlıkları: her test geçici, boş bir veri tabanıyla çalışır."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from server.db import session as db_session
from shared import config


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """bcrypt'in gerçek ayarı (12 tur) testleri çok yavaşlatır."""
    monkeypatch.setattr(config, "BCRYPT_ROUNDS", 4)


@pytest.fixture(autouse=True)
def temp_events_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Olay logu geçici dosyaya yazılsın; gerçek logs/events.log kirlenmesin."""
    path = tmp_path / "events.log"
    monkeypatch.setattr(config, "EVENTS_LOG_PATH", path)
    return path


@pytest.fixture
def empty_db(tmp_path: Path) -> Iterator[Path]:
    """Geçici dosyada boş şema. Gerçek data/labsinav.db'ye dokunulmaz."""
    db_path = tmp_path / "test.db"
    db_session.configure(db_path)
    db_session.reset_db()
    yield db_path
    db_session.get_engine().dispose()


@pytest.fixture
def seeded_db(empty_db: Path) -> Path:
    """Örnek verilerle doldurulmuş geçici veri tabanı."""
    from scripts.seed import seed

    with db_session.get_session() as session:
        seed(session)
    return empty_db
