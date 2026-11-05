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
