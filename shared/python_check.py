"""Python sürümü kontrolü (iki uygulama için ortak).

Neden: Python 3.15'te standart kütüphanedeki asyncio.to_thread
"TypeError: 'lazy_import' object is not callable" hatası veriyor; sunucu çalışmıyor.
Hata bizim kodumuzda değil. Uygulama 3.11–3.14 ile test edildi.
Daha yeni bir sürümde kullanıcı uyarılır ama uygulama yine açılır.
(Paketlenmiş .exe kendi Python'unu içerir; orada bu uyarı hiç çıkmaz.)
"""

import sys

from PySide6.QtWidgets import QMessageBox, QWidget

MAX_TESTED = (3, 14)  # test edilen en yeni sürüm


def unsupported_python_message(version: tuple[int, ...] = tuple(sys.version_info)) -> str | None:
    """Python test edilenden yeniyse Türkçe uyarı metni, değilse None."""
    if tuple(version[:2]) <= MAX_TESTED:
        return None
    current = ".".join(str(part) for part in version[:3])
    return (
        f"Bu uygulama Python 3.11–3.14 ile test edildi, lütfen 3.14 kurun.\n\n"
        f"Şu an çalışan sürüm: Python {current}\n"
        "Bu sürümde sunucu düzgün çalışmayabilir. Ayrıntı: docs/SORUN_GIDERME.md"
    )


def warn_if_unsupported_python(parent: QWidget | None = None) -> None:
    """Gerekirse uyarı penceresi gösterir; kapatılınca uygulama açılmaya devam eder."""
    message = unsupported_python_message()
    if message is not None:
        QMessageBox.warning(parent, "Python sürümü", message)
