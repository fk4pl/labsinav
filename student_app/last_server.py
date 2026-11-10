"""Son bağlanılan sunucuyu hatırlama. (Sahibi: C)

Neden: Okul WiFi'ları çoğu zaman UDP broadcast'i engeller; otomatik bulma çalışmaz.
Öğrenci bir kez IP'yi elle girip bağlandıysa bir sonraki açılışta aynı IP önce denenir
ve IP kutusuna hazır yazılır; her sınavda yeniden yazmak gerekmez.

Dosya: kullanıcı uygulama veri klasöründe last_server.json, ör.
    Windows: C:\\Users\\<ad>\\AppData\\Local\\LabSinav\\last_server.json

Bu modül Qt kullanmaz; pytest ile kolayca test edilir.
"""

import json
import logging
import socket
from pathlib import Path

import platformdirs

from shared import config

logger = logging.getLogger(__name__)

REACH_TIMEOUT_SEC = 1.0  # son sunucuya bağlanmayı bu kadar dene


def default_path() -> Path:
    return Path(platformdirs.user_data_dir(config.APP_DIR_NAME, appauthor=False)) / "last_server.json"


def load_last_server(path: Path) -> tuple[str, int] | None:
    """Kayıtlı (host, port). Dosya yoksa ya da bozuksa None (uygulama çökmez)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        host, port = str(data["host"]), int(data["port"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError):
        logger.warning("Son sunucu dosyası okunamadı: %s", path, exc_info=True)
        return None
    if not host or not 0 < port < 65536:
        return None
    return host, port


def save_last_server(path: Path, host: str, port: int) -> None:
    """Başarılı girişten sonra çağrılır. Yazılamazsa sadece loglanır."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"host": host, "port": port}), encoding="utf-8")
    except OSError:
        logger.warning("Son sunucu kaydedilemedi: %s", path, exc_info=True)


def is_reachable(host: str, port: int, timeout: float = REACH_TIMEOUT_SEC) -> bool:
    """Sunucu portu TCP bağlantısı kabul ediyor mu? (bloklar: ayrı thread'de çağırın)"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
