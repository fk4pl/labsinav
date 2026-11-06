"""Ortak hata yakalayıcı: yakalanmamış hata loglanır ve Türkçe mesaj gösterilir."""

import logging
import sys
import threading
from pathlib import Path

import pytest

from tests.qt_utils import qapp  # QT_QPA_PLATFORM'u ayarlar

from shared import app_errors, config


@pytest.fixture
def restore_logging_and_hooks():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    hook, thread_hook = sys.excepthook, threading.excepthook
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers, root.level = handlers, level
    sys.excepthook, threading.excepthook = hook, thread_hook


def test_setup_logging_writes_to_file(tmp_path: Path, monkeypatch, restore_logging_and_hooks) -> None:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    app_errors.setup_logging("deneme")
    logging.getLogger("x").info("merhaba")
    assert "merhaba" in (tmp_path / "deneme.log").read_text("utf-8")


def test_uncaught_exception_is_logged_and_user_sees_turkish_message(
    tmp_path: Path, monkeypatch, restore_logging_and_hooks
) -> None:
    qapp()
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    app_errors.setup_logging("deneme")
    shown: list[str] = []
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda _p, _t, text: shown.append(text)))
    app_errors.install_error_handler()
    try:
        raise ZeroDivisionError("bölme hatası")
    except ZeroDivisionError:
        sys.excepthook(*sys.exc_info())

    log_text = (tmp_path / "deneme.log").read_text("utf-8")
    assert "ZeroDivisionError" in log_text           # traceback log dosyasında
    assert len(shown) == 1
    assert "Beklenmeyen bir hata oluştu" in shown[0]  # kullanıcıya Türkçe mesaj
    assert "Traceback" not in shown[0] and "ZeroDivisionError" not in shown[0]
