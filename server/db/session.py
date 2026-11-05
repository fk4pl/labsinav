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

from sqlalchemy import Engine, create_engine, event
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


def init_db() -> None:
    """Eksik tabloları oluşturur (var olanlara dokunmaz)."""
    Base.metadata.create_all(get_engine())


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
