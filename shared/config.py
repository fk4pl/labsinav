"""Uygulama genelindeki sabitler (port, dosya yolları, süreler).

Bu dosyayı değiştirmek ekip onayı gerektirir.
"""

import sys
from pathlib import Path

import platformdirs

# --- Ağ ---
WS_PORT = 8765                    # WebSocket sunucusunun portu
DISCOVERY_PORT = 50555            # UDP broadcast ile sunucu keşfi
DISCOVERY_MAGIC = b"LABSINAV_DISCOVER"  # istemcinin yolladığı keşif mesajı
SERVICE_NAME = "labsinav"         # sunucunun keşif cevabındaki kimliği
DISCOVERY_TIMEOUT_SEC = 2.0
MAX_MESSAGE_BYTES = 1_000_000     # tek bir WebSocket mesajının üst sınırı (1 MB)

# --- Zamanlama ---
PING_INTERVAL_SEC = 10            # istemci bu aralıkla ping yollar
SAVE_DEBOUNCE_SEC = 2             # otomatik kayıt gecikmesi

# --- Puan ---
# Bir sorunun puanı (soru bankasındaki varsayılan puan ve sınavdaki puan) bu aralıkta olmalı.
# Hem arayüzdeki sayı kutuları hem servislerdeki doğrulama bu sabitleri kullanır.
MIN_QUESTION_POINTS = 0.5
MAX_QUESTION_POINTS = 100.0

# --- Güvenlik ---
BCRYPT_ROUNDS = 12                # testlerde hız için düşürülür

# --- Dosya yolları ---
# Geliştirirken (python -m ...) data/ ve logs/ repo klasörünün içindedir.
# Paketlenmiş .exe'de (PyInstaller, sys.frozen) program klasörüne yazılamayabilir;
# bu yüzden kullanıcının uygulama veri klasörü kullanılır, ör.
#     Windows: C:\Users\<ad>\AppData\Local\LabSinav\data  ve  ...\LabSinav\logs
APP_DIR_NAME = "LabSinav"
BASE_DIR = Path(__file__).resolve().parent.parent
IS_FROZEN = bool(getattr(sys, "frozen", False))


def runtime_dirs(frozen: bool) -> tuple[Path, Path]:
    """(veri klasörü, log klasörü). frozen: .exe olarak mı çalışıyoruz?"""
    if frozen:
        user_dir = Path(platformdirs.user_data_dir(APP_DIR_NAME, appauthor=False))
        return user_dir / "data", user_dir / "logs"
    return BASE_DIR / "data", BASE_DIR / "logs"


DATA_DIR, LOG_DIR = runtime_dirs(IS_FROZEN)
DB_PATH = DATA_DIR / "labsinav.db"
EVENTS_LOG_PATH = LOG_DIR / "events.log"


def ensure_runtime_dirs() -> None:
    """data/ ve logs/ klasörleri yoksa oluşturur (git'te tutulmazlar)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
