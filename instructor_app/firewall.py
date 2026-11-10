"""Windows güvenlik duvarı kontrolü (eğitmen uygulaması). (Sahibi: B)

Sorun: Windows güvenlik duvarı gelen bağlantıları varsayılan olarak engeller; öğrenciler
sunucuyu bulamaz/bağlanamaz. Bu modül iki kuralın (TCP 8765, UDP 50555) var olup
olmadığını kontrol eder ve yoksa yönetici izniyle (UAC penceresi) ekler.

Linux/macOS'ta hiçbir şey yapmaz: missing_rules() boş liste döner.

Kontrol için netsh'in ÇIKIŞ KODUNA bakılır (kural bulunamazsa 1 döner); çıktı metnine
bakılmaz çünkü Türkçe Windows'ta metin Türkçedir.
"""

import logging
import subprocess
import sys
from dataclasses import dataclass

from shared import config

logger = logging.getLogger(__name__)

NETSH_TIMEOUT_SEC = 5


@dataclass(frozen=True)
class FirewallRule:
    name: str
    protocol: str  # "TCP" veya "UDP"
    port: int


# Adlar README'deki elle ekleme komutlarıyla aynı: elle eklenmiş kural da tanınır.
RULES = [
    FirewallRule("LabSinav WebSocket", "TCP", config.WS_PORT),
    FirewallRule("LabSinav Kesif", "UDP", config.DISCOVERY_PORT),
]


def is_windows() -> bool:
    return sys.platform == "win32"


def add_rule_command(rule: FirewallRule) -> str:
    """Kuralı ekleyen netsh komutu (kullanıcıya da gösterilir)."""
    return (
        f'netsh advfirewall firewall add rule name="{rule.name}" dir=in action=allow '
        f"protocol={rule.protocol} localport={rule.port}"
    )


def _rule_exists(rule: FirewallRule) -> bool:
    command = ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule.name}"]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=NETSH_TIMEOUT_SEC,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # siyah pencere açılmasın
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("Güvenlik duvarı kuralı kontrol edilemedi: %s", rule.name, exc_info=True)
        return True  # kontrol edemiyorsak kullanıcıyı boş yere uyarmayalım
    return result.returncode == 0


def missing_rules() -> list[FirewallRule]:
    """Eksik kurallar. Windows değilse her zaman boş liste."""
    if not is_windows():
        return []
    return [rule for rule in RULES if not _rule_exists(rule)]


def add_rules_elevated(rules: list[FirewallRule]) -> bool:
    """Kuralları yönetici olarak ekler (Windows UAC onay penceresi açılır).

    True: komut başlatıldı (kullanıcı UAC'de "Evet" dediyse kurallar eklenir).
    False: başlatılamadı ya da kullanıcı "Hayır" dedi.
    """
    if not is_windows() or not rules:
        return False
    import ctypes  # sadece Windows'ta gerekli

    # Tek bir UAC onayı için iki komut cmd.exe ile art arda çalıştırılır.
    arguments = "/c " + " & ".join(add_rule_command(rule) for rule in rules)
    sw_hide = 0
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", arguments, None, sw_hide)
    return int(result) > 32  # ShellExecute: 32'den büyük değer başarı demektir
