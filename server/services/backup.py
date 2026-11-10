"""Veri tabanı yedeği (eğitmen uygulaması: Ayarlar → Veri tabanını yedekle…).

Neden dosyayı düz kopyalamıyoruz? Veri tabanı WAL modunda çalışır: son yazmalar bir süre
labsinav.db-wal dosyasında bekler. Sadece labsinav.db kopyalanırsa bu yazmalar eksik kalır.
SQLite'ın kendi backup() fonksiyonu WAL'dekiler dahil tutarlı bir kopya üretir;
sunucu çalışırken (sınav sırasında bile) güvenle kullanılabilir.
"""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from server.db.session import get_engine


def default_backup_name(now: datetime) -> str:
    """Tarihli dosya adı, ör. labsinav_yedek_2026-11-10_14-30.db"""
    return f"labsinav_yedek_{now:%Y-%m-%d_%H-%M}.db"


def current_db_path() -> Path:
    """Uygulamanın şu an kullandığı veri tabanı dosyası (testlerde geçici dosya)."""
    return Path(get_engine().url.database or "")


def backup_database(target: Path, source: Path | None = None) -> Path:
    """source veri tabanını (varsayılan: uygulamanın kullandığı dosya) target'a kopyalar.

    Disk hatasında OSError / sqlite3.Error fırlar; çağıran kullanıcıya mesaj gösterir.
    """
    source = source or current_db_path()
    if not source.exists():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    # closing(): bağlantılar iş bitince kapansın (Windows'ta dosya kilitli kalmasın).
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    return target
