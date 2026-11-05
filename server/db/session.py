"""Veri tabanı bağlantısı.

Kullanım:
    from server.db.session import get_session

    with get_session() as session:
        user = session.scalar(select(User).where(...))
        ...
    # blok hatasız biterse commit, hata olursa rollback yapılır.

YAZMA KURALI: Veri tabanına yazan kod get_session() yerine write_session() kullanır.
write_session() tek bir kilit (lock) alır; böylece 40 öğrenci aynı anda cevap kaydetse de
yazmalar sırayla yapılır ve SQLite "database is locked" hatası vermez. Sadece okuma
yapan kod get_session() kullanabilir (WAL modu sayesinde okuma yazmayı beklemez).
"""

import threading

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from server.db.models import Base
from shared import config

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_write_lock = threading.Lock()  # aynı anda yalnızca bir yazma işlemi


def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """Her yeni bağlantıda çalışır.
    WAL: okuma ve yazma aynı anda yapılabilir (sunucu yazarken arayüz okuyabilir).
    foreign_keys: SQLite'ta yabancı anahtar kontrolü varsayılan olarak kapalıdır."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def configure(db_path: Path | str = config.DB_PATH) -> Engine:
    """Veri tabanı dosyasını seçer. Testler geçici bir dosya vermek için kullanır."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: sunucu thread'i ve arayüz thread'i aynı engine'i kullanır.
    _engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    event.listen(_engine, "connect", _set_sqlite_pragmas)
    # expire_on_commit=False: session kapandıktan sonra da nesnenin alanları okunabilir.
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


# Şemaya SONRADAN eklenen sütunlar: (tablo, sütun, SQL tanımı).
# create_all() var olan tabloya sütun eklemez; eski veri tabanı dosyası olan biri
# git pull yapınca uygulama çökmesin diye bu sütunlar init_db()'de elle eklenir.
# Yeni sütun eklerken buraya da bir satır ekleyin (DEFAULT değeri olmalı).
ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("answers", "is_manual", "BOOLEAN NOT NULL DEFAULT 0"),
]


def init_db() -> None:
    """Eksik tabloları oluşturur (var olanlara dokunmaz), eksik sütunları ekler."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """ADDED_COLUMNS'taki sütunlardan tabloda olmayanları ALTER TABLE ile ekler."""
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, column, definition in ADDED_COLUMNS:
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def reset_db() -> None:
    """TÜM tabloları silip yeniden oluşturur. Sadece seed ve testler için."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@contextmanager
def get_session() -> Iterator[Session]:
    """Commit/rollback'i otomatik yapan oturum."""
    get_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def write_session() -> Iterator[Session]:
    """Yazma yapan işlemler için oturum: kilit alınır, iş bitince commit edilir.

    Kilidin içindeyken uzun iş (derleme, ağ beklemesi) YAPMAYIN; diğer yazmalar bekler.
    """
    with _write_lock:
        with get_session() as session:
            yield session
