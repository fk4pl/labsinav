"""Öğrenci uygulamasının dayanıklılığı: sınav modu, bağlantı kopması, yerel yedek, kiosk kaçış yolu.

Sunucu yerine DemoBackend kullanılır (aynı sinyaller). Sunucu saati ServerClock.update() ile
ileri alınarak "süre doldu" durumu beklemeden denenir.
"""

from datetime import timedelta
from pathlib import Path

from tests.qt_utils import qapp, qt_wait_until  # önce gelmeli (offscreen)

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from student_app import main as student_main
from student_app.demo import DemoBackend
from student_app.main import OFFLINE_EXPIRED_TEXT, StudentWindow, parse_args
from student_app.net.client import ConnectionState
from student_app.ui.exam_view import OFFLINE_EXPIRY_GRACE_SEC

TEXT_QUESTION_INDEX = 3  # demo_exam.json'daki 4. soru (klasik, id=4)
TEXT_QUESTION_ID = 4


def start_window(backup_dir: Path | None, kiosk: bool = True) -> tuple[StudentWindow, DemoBackend]:
    qapp()
    backend = DemoBackend(30)
    window = StudentWindow(backend, kiosk=kiosk, backup_dir=backup_dir)
    backend.start()  # giriş + exam_start
    return window, backend


def type_answer(window: StudentWindow, text: str) -> None:
    view = window.exam_view
    view.go_to(TEXT_QUESTION_INDEX)
    view._pages[TEXT_QUESTION_INDEX].editor._edit.setPlainText(text)


def go_offline(backend: DemoBackend) -> None:
    backend.connection_changed.emit(ConnectionState.RECONNECTING)


def jump_past_end(window: StudentWindow, seconds: float) -> None:
    """Sunucu saatini bitişin 'seconds' sn sonrasına al ve geri sayımı bir kez çalıştır."""
    view = window.exam_view
    assert view._ends_at is not None
    window.backend.clock.update(view._ends_at + timedelta(seconds=seconds))
    view._on_countdown_tick()


def test_no_kiosk_flag() -> None:
    assert parse_args(["--no-kiosk"]).no_kiosk
    assert not parse_args([]).no_kiosk


def test_offline_banner_and_backup_written(tmp_path: Path) -> None:
    window, backend = start_window(tmp_path)
    view = window.exam_view
    assert view.offline_banner.isHidden()

    go_offline(backend)
    assert not view.offline_banner.isHidden()
    assert "Bağlantı koptu" in view.offline_banner.text()

    type_answer(window, "çevrimdışı cevap")
    assert view.backup_path is not None
    assert "çevrimdışı cevap" in view.backup_path.read_text(encoding="utf-8")

    backend.connection_changed.emit(ConnectionState.CONNECTED)
    assert view.offline_banner.isHidden()
    qt_wait_until(lambda: TEXT_QUESTION_ID in backend.saved)  # bağlantı gelince gönderildi
    assert backend.saved[TEXT_QUESTION_ID].text_answer == "çevrimdışı cevap"
    backend.close()


def test_restart_restores_answers_from_backup(tmp_path: Path) -> None:
    """Uygulama kapanıp açılınca (yeni pencere) yedekteki gönderilmemiş cevap geri gelir ve gönderilir."""
    window, backend = start_window(tmp_path)
    go_offline(backend)
    type_answer(window, "çökmeden önce")
    backend.close()  # "çöktü": cevap sunucuya hiç gitmedi

    window2, backend2 = start_window(tmp_path)
    view2 = window2.exam_view
    assert view2.state.answer_for(TEXT_QUESTION_ID).text_answer == "çökmeden önce"
    assert view2._pages[TEXT_QUESTION_INDEX].editor.value().text_answer == "çökmeden önce"
    qt_wait_until(lambda: TEXT_QUESTION_ID in backend2.saved)
    assert backend2.saved[TEXT_QUESTION_ID].text_answer == "çökmeden önce"
    backend2.close()


def test_submit_deletes_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window, backend = start_window(tmp_path)
    view = window.exam_view
    type_answer(window, "son cevap")
    path = view.backup_path
    assert path is not None and path.exists()

    monkeypatch.setattr(view, "_confirm_finish", lambda: True)
    view._on_finish_clicked()
    qt_wait_until(lambda: window.pages.currentWidget() is window.finished_page)
    assert not path.exists()
    backend.close()


def test_kiosk_blocks_close_during_exam(tmp_path: Path) -> None:
    window, backend = start_window(tmp_path, kiosk=True)
    window.show()
    assert window.is_exam_locked()
    assert window.close() is False  # ×, Alt+F4 reddedilir
    assert window.isVisible()
    assert "kapatılamaz" in window.exam_view.banner.text()
    backend.close()
    window.hide()


def test_no_kiosk_allows_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window, backend = start_window(tmp_path, kiosk=False)
    window.show()
    assert not window.is_exam_locked()
    monkeypatch.setattr(student_main.QMessageBox, "question",
                        lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    assert window.close() is True


def test_focus_lost_shows_warning(tmp_path: Path) -> None:
    window, backend = start_window(tmp_path, kiosk=False)
    window.show()
    sent: list[int] = []
    window.exam_view.focus_lost.connect(sent.append)
    window.exam_view._on_app_state_changed(Qt.ApplicationState.ApplicationInactive)
    assert sent == [window.exam_view.exam_id]
    assert window.exam_view.banner.text() == "Pencereden çıkış kaydedildi."
    backend.close()
    window.hide()


def test_time_up_without_server_unlocks_kiosk_and_keeps_backup(tmp_path: Path) -> None:
    """Sunucu çöktü ve süre doldu: öğrenci kilitli kalmaz, yedek silinmez."""
    window, backend = start_window(tmp_path, kiosk=True)
    window.show()
    view = window.exam_view
    type_answer(window, "sunucuya gitmedi")
    go_offline(backend)

    jump_past_end(window, OFFLINE_EXPIRY_GRACE_SEC - 5)  # henüz pay süresi içinde
    assert window.pages.currentWidget() is view and window.is_exam_locked()

    jump_past_end(window, OFFLINE_EXPIRY_GRACE_SEC + 1)
    assert window.pages.currentWidget() is window.finished_page
    assert window.finished_page.title_label.text() == "Sunucuya ulaşılamadı"
    assert OFFLINE_EXPIRED_TEXT in window.finished_page.detail_label.text()
    assert view.backup_path is not None and view.backup_path.exists()
    assert "sunucuya gitmedi" in view.backup_path.read_text(encoding="utf-8")
    assert not window.is_exam_locked()

    # Sonradan bağlantı gelip sunucu exam_end yollasa bile yedek silinmez.
    backend.connection_changed.emit(ConnectionState.CONNECTED)
    view.finish()
    assert view.backup_path.exists()
    assert window.close() is True


def test_time_up_while_connected_waits_for_server(tmp_path: Path) -> None:
    """Bağlantı varken kaçış yolu devreye girmez; sunucunun exam_end'i beklenir."""
    window, backend = start_window(tmp_path, kiosk=True)
    jump_past_end(window, OFFLINE_EXPIRY_GRACE_SEC + 60)
    assert window.pages.currentWidget() is window.exam_view
    assert window.is_exam_locked()
    backend.close()
