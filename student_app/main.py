"""Öğrenci uygulaması: python -m student_app.main  (Sahibi: C)

    python -m student_app.main                         gerçek sunucuyla
    python -m student_app.main --demo                  sunucusuz deneme (cevaplar bellekte)
    python -m student_app.main --demo --demo-minutes 6 5 ve 1 dakika uyarılarını hızlı görmek için

Ekran akışı:
    giriş → bekleme → sınav → gönderildi
Bağlantı koparsa sınav ekranında kalınır; istemci kendisi yeniden bağlanır ve giriş yapar,
sunucu exam_start'ı kayıtlı cevaplarla tekrar yollar.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

from server.net.discovery import discover_server
from shared.protocol import (
    ErrorCode,
    ExamEnd,
    ExamStart,
    ExamUpdate,
    MsgType,
    SaveAnswerRequest,
    SubmitOk,
    SubmitRequest,
    UserInfo,
)
from student_app.demo import DemoBackend
from student_app.net.client import ServerClient
from student_app.ui.exam_view import ExamView
from student_app.ui.finished import FinishedPage
from student_app.ui.login import LoginPage
from student_app.ui.style import FULL_STYLESHEET
from student_app.ui.waiting import WaitingPage
from student_app.ui.zoom import FontZoom

# Bu hatalar geldiğinde sınav bu öğrenci için bitmiştir: "gönderildi" ekranına geçilir.
EXAM_OVER_ERRORS = {
    ErrorCode.TIME_UP: "Süre doldu. Kaydedilmiş cevapların otomatik olarak gönderildi.",
    ErrorCode.ALREADY_SUBMITTED: "Bu sınavı zaten göndermiştin.",
    ErrorCode.EXAM_NOT_ACTIVE: "Sınav sona erdi. Kaydedilmiş cevapların gönderildi.",
}
EXAM_END_REASONS = {
    "time_up": "Süre doldu. Kaydedilmiş cevapların otomatik olarak gönderildi.",
    "instructor_stopped": "Sınav eğitmen tarafından bitirildi. Kaydedilmiş cevapların gönderildi.",
}


class DiscoveryThread(QThread):
    """discover_server() bloklayan bir fonksiyon; arayüz donmasın diye ayrı thread'de çalışır."""

    finished_with_result = Signal(object)  # (host, port) veya None

    def run(self) -> None:
        self.finished_with_result.emit(discover_server())


class StudentWindow(QMainWindow):
    def __init__(self, backend: ServerClient | DemoBackend, zoom: FontZoom | None = None) -> None:
        super().__init__()
        self.setWindowTitle("LabSınav — Öğrenci")
        self.resize(1100, 720)
        self.backend = backend   # gerçek sunucu istemcisi ya da --demo'daki sahte sunucu
        self.zoom = zoom
        self._user: UserInfo | None = None
        self._discovery: DiscoveryThread | None = None

        self.login_page = LoginPage()
        self.login_page.login_requested.connect(self._on_login_requested)
        self.login_page.rediscover_requested.connect(self.start_discovery)
        self.waiting_page = WaitingPage()
        self.exam_view = ExamView(backend.clock)
        self.finished_page = FinishedPage()

        self.pages = QStackedWidget()
        for page in (self.login_page, self.waiting_page, self.exam_view, self.finished_page):
            self.pages.addWidget(page)
        self.setCentralWidget(self.pages)

        self._connect_backend()
        self._connect_exam_view()
        self._create_zoom_shortcuts()

    # ------------------------------------------------------------------
    # Bağlantılar
    # ------------------------------------------------------------------

    def _connect_backend(self) -> None:
        b = self.backend
        b.logged_in.connect(self._on_logged_in)
        b.login_failed.connect(self._on_login_failed)
        b.connection_error.connect(self._on_login_failed)
        b.connection_lost.connect(self._back_to_login)
        b.session_replaced.connect(
            lambda: self._back_to_login("Bu hesapla başka bir bilgisayardan giriş yapıldı.")
        )
        b.connection_changed.connect(self.exam_view.set_connection_state)
        b.connection_changed.connect(self.waiting_page.set_connection_state)
        b.exam_started.connect(self._on_exam_started)
        b.exam_updated.connect(self._on_exam_updated)
        b.exam_ended.connect(self._on_exam_ended)
        b.save_confirmed.connect(self.exam_view.on_save_ok)
        b.submit_confirmed.connect(self._on_submit_confirmed)
        b.error_received.connect(self._on_error)

    def _connect_exam_view(self) -> None:
        self.exam_view.save_requested.connect(self._on_save_requested)
        self.exam_view.submit_requested.connect(
            lambda exam_id: self.backend.request(MsgType.SUBMIT, SubmitRequest(exam_id=exam_id))
        )
        self.exam_view.focus_lost.connect(self.backend.send_focus_lost)

    def _create_zoom_shortcuts(self) -> None:
        if self.zoom is None:
            return
        # Türkçe klavyede "+" farklı yerde olabilir; birkaç kısayolu birden tanımlıyoruz.
        for keys, action in (
            (QKeySequence.StandardKey.ZoomIn, self.zoom.zoom_in),
            ("Ctrl+=", self.zoom.zoom_in),
            ("Ctrl+Shift++", self.zoom.zoom_in),
            (QKeySequence.StandardKey.ZoomOut, self.zoom.zoom_out),
            ("Ctrl+0", self.zoom.reset),
        ):
            QShortcut(QKeySequence(keys), self, activated=action)
        self.exam_view.zoom_in_requested.connect(self.zoom.zoom_in)
        self.exam_view.zoom_out_requested.connect(self.zoom.zoom_out)

    # ------------------------------------------------------------------
    # Sunucu keşfi ve giriş
    # ------------------------------------------------------------------

    def start_discovery(self) -> None:
        if self._discovery is not None and self._discovery.isRunning():
            return
        self.login_page.set_searching()
        self._discovery = DiscoveryThread(self)
        self._discovery.finished_with_result.connect(self._on_discovery_result)
        self._discovery.start()

    def _on_discovery_result(self, result: tuple[str, int] | None) -> None:
        if result is None:
            self.login_page.set_server_not_found()
        else:
            self.login_page.set_server_found(*result)

    def _on_login_requested(self, host: str, port: int, username: str, password: str) -> None:
        self.login_page.set_busy(True)
        self.backend.login(host, port, username, password)

    def _on_login_failed(self, message: str) -> None:
        self.login_page.set_busy(False)
        self.login_page.reset_password()
        self.login_page.show_error(message)

    def _on_logged_in(self, user: UserInfo) -> None:
        if self._user is not None and self._user.username != user.username:
            self.exam_view.reset()  # başka öğrenci: öncekinin cevapları taşınmasın
        self._user = user
        self.login_page.set_busy(False)
        self.login_page.reset_password()
        self.waiting_page.show_user(user)
        # Yeniden bağlanınca sınav/gönderildi ekranında kal; sunucu gerekirse exam_start yollar.
        if self.pages.currentWidget() is self.login_page:
            self.pages.setCurrentWidget(self.waiting_page)

    def _back_to_login(self, reason: str) -> None:
        """Bağlantı koptu ve tekrar denenmeyecek: öğrenci yeniden giriş yapmalı."""
        self.login_page.set_busy(False)
        self.login_page.reset_password()
        if self.pages.currentWidget() is self.exam_view:
            reason += " Tekrar giriş yapınca kaldığın yerden devam edeceksin."
        else:
            reason += " Lütfen tekrar giriş yapın."
        self.login_page.show_error(reason)
        self.pages.setCurrentWidget(self.login_page)

    # ------------------------------------------------------------------
    # Sınav
    # ------------------------------------------------------------------

    def _on_exam_started(self, start: ExamStart) -> None:
        # Aynı exam_start iki kez gelebilir (yeniden bağlanma): ExamView bunu kendisi ayırt eder.
        self.exam_view.load_exam(start, self._user)
        self.pages.setCurrentWidget(self.exam_view)

    def _on_exam_updated(self, update: ExamUpdate) -> None:
        if update.exam_id == self.exam_view.exam_id:
            self.exam_view.update_end_time(update.ends_at)

    def _on_exam_ended(self, end: ExamEnd) -> None:
        if end.exam_id != self.exam_view.exam_id:
            return
        self._show_finished(datetime.now(timezone.utc), EXAM_END_REASONS[end.reason])

    def _on_submit_confirmed(self, reply: SubmitOk) -> None:
        self._show_finished(reply.submitted_at, "Cevapların kaydedildi. Pencereyi kapatabilirsin.")

    def _on_save_requested(self, request: SaveAnswerRequest) -> None:
        self.backend.request(MsgType.SAVE_ANSWER, request)

    def _on_error(self, code: str, message: str, request_type: str) -> None:
        if code in EXAM_OVER_ERRORS and request_type in (MsgType.SAVE_ANSWER, MsgType.SUBMIT):
            self._show_finished(datetime.now(timezone.utc), EXAM_OVER_ERRORS[code])
        elif request_type in (MsgType.SAVE_ANSWER, MsgType.SUBMIT):
            self.exam_view.on_request_failed(request_type, message)
        else:
            logging.info("Sunucu hatası (%s): %s", code, message)

    def _show_finished(self, at: datetime, detail: str) -> None:
        if self.pages.currentWidget() is self.finished_page:
            return  # zaten gösteriliyor (ör. exam_end'den sonra TIME_UP da geldi)
        self.exam_view.stop()
        self.finished_page.show_result(at, detail)
        self.pages.setCurrentWidget(self.finished_page)

    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.pages.currentWidget() is self.exam_view and self.exam_view.is_active:
            answer = QMessageBox.question(
                self, "Sınav devam ediyor",
                "Sınav henüz bitmedi. Uygulamayı kapatmak istiyor musun?\n"
                "Kaydedilmiş cevapların kaybolmaz; tekrar giriş yaparak devam edebilirsin.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.exam_view.flush_saves()
        self.backend.close()
        if self._discovery is not None:
            self._discovery.wait()  # keşif en fazla birkaç saniye sürer
        event.accept()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LabSınav öğrenci uygulaması")
    parser.add_argument("--demo", action="store_true", help="sunucusuz deneme modu")
    parser.add_argument("--demo-minutes", type=float, default=30, help="demo sınav süresi (dakika)")
    args, _unknown = parser.parse_known_args(argv)  # Qt'nin kendi argümanlarını yoksay
    return args


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(sys.argv[1:])
    app = QApplication(sys.argv)
    app.setApplicationName("LabSınav Öğrenci")
    zoom = FontZoom(app, FULL_STYLESHEET)

    if args.demo:
        backend = DemoBackend(args.demo_minutes)
        window = StudentWindow(backend, zoom)
        window.setWindowTitle("LabSınav — Öğrenci (DEMO)")
        window.show()
        backend.start()
    else:
        window = StudentWindow(ServerClient(), zoom)
        window.show()
        window.start_discovery()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
