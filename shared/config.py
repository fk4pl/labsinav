"""Uygulama genelindeki sabitler (port, dosya yolları, süreler).

Bu dosyayı değiştirmek ekip onayı gerektirir (CLAUDE.md).
"""

from pathlib import Path

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

# --- Güvenlik ---
BCRYPT_ROUNDS = 12                # testlerde hız için düşürülür

# --- Dosya yolları ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "labsinav.db"
LOG_DIR = BASE_DIR / "logs"
EVENTS_LOG_PATH = LOG_DIR / "events.log"


def ensure_runtime_dirs() -> None:
    """data/ ve logs/ klasörleri yoksa oluşturur (git'te tutulmazlar)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
