"""Qt kullanan testler için yardımcılar (ekransız çalışır)."""

import os
import time
from collections.abc import Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # PySide6 import edilmeden önce

from PySide6.QtWidgets import QApplication  # noqa: E402


def qapp() -> QApplication:
    """Tek bir QApplication (Qt aynı anda birden fazlasına izin vermez)."""
    return QApplication.instance() or QApplication([])


def qt_wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Koşul sağlanana kadar Qt olaylarını işler (sinyaller bu sırada gelir)."""
    app = qapp()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Koşul zamanında sağlanmadı")
