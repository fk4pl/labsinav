"""Öğrenci uygulaması: sunucu bulunamazsa kendiliğinden tekrar arama."""

from tests.qt_utils import qapp, qt_wait_until  # önce gelmeli (offscreen)

import pytest

from student_app import main as student_main
from student_app.demo import DemoBackend
from student_app.main import StudentWindow


def test_keeps_searching_until_server_found(monkeypatch: pytest.MonkeyPatch) -> None:
    qapp()
    answers = [None, None, ("192.168.1.10", 8765)]  # iki kez bulunamaz, üçüncüde bulunur
    calls: list[int] = []

    def fake_discover() -> tuple[str, int] | None:
        calls.append(1)
        return answers[min(len(calls), len(answers)) - 1]

    monkeypatch.setattr(student_main, "discover_server", fake_discover)
    monkeypatch.setattr(student_main, "DISCOVERY_RETRY_MS", 20)
    window = StudentWindow(DemoBackend(30))  # backend kullanılmaz; sadece giriş ekranı
    page = window.login_page

    window.start_discovery()
    qt_wait_until(lambda: "tekrar aranıyor" in page.server_label.text())
    assert not page.address_row.isHidden()  # elle IP alanı açık kalır

    page.address_input.setText("10.0.0")  # öğrenci yazarken tekrar arama alanı silmemeli
    qt_wait_until(lambda: page.has_server())
    assert len(calls) == 3
    assert page.server_label.text() == "Sunucu bulundu: 192.168.1.10:8765"
    assert page.address_row.isHidden()

    window._retry_timer.stop()
    window._discovery.wait()


def test_no_retry_after_leaving_login_page(monkeypatch: pytest.MonkeyPatch) -> None:
    qapp()
    calls: list[int] = []
    monkeypatch.setattr(student_main, "discover_server", lambda: calls.append(1))
    monkeypatch.setattr(student_main, "DISCOVERY_RETRY_MS", 20)
    window = StudentWindow(DemoBackend(30))

    window.start_discovery()
    qt_wait_until(lambda: calls and not window._is_discovering())
    window.pages.setCurrentWidget(window.waiting_page)  # ör. elle IP ile giriş yapıldı
    count = len(calls)
    with pytest.raises(AssertionError):  # 0,2 sn (≈10 zamanlayıcı turu) boyunca yeni arama olmamalı
        qt_wait_until(lambda: len(calls) > count, timeout=0.2)
    window._retry_timer.stop()
