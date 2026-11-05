"""Öğrenci uygulaması: python -m student_app.main  (Sahibi: C)

Akış: sunucuyu ara → giriş ekranı → (login_ok) → bekleme ekranı.
"""

import logging
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from server.net.discovery import discover_server
from shared.protocol import (
    Envelope,
    ErrorPayload,
    LoginOk,
    LoginRequest,
    MsgType,
    ProtocolError,
    parse_payload,
)
from shared.theme import STYLESHEET
from student_app.net.client import ServerClient
from student_app.ui.login import LoginPage
from student_app.ui.waiting import WaitingPage


class DiscoveryThread(QThread):
    """discover_server() bloklayan bir fonksiyon; arayüz donmasın diye ayrı thread'de çalışır."""

    finished_with_result = Signal(object)  # (host, port) veya None

    def run(self) -> None:
        self.finished_with_result.emit(discover_server())


class StudentWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LabSınav — Öğrenci")
        self.resize(900, 640)

        self.client = ServerClient(self)
        self.client.connected.connect(self._on_connected)
        self.client.disconnected.connect(self._on_disconnected)
        self.client.connection_error.connect(self._on_connection_error)
        self.client.message_received.connect(self._on_message)

        self.login_page = LoginPage()
        self.login_page.login_requested.connect(self._on_login_requested)
        self.login_page.rediscover_requested.connect(self.start_discovery)
        self.waiting_page = WaitingPage()

        self.pages = QStackedWidget()
        self.pages.addWidget(self.login_page)
        self.pages.addWidget(self.waiting_page)
        self.setCentralWidget(self.pages)

        self._pending_login: LoginRequest | None = None  # bağlantı kurulunca gönderilecek
        self._login_msg_id: str | None = None
        self._discovery: DiscoveryThread | None = None

    # --- Sunucu keşfi ---

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

    # --- Giriş ---

    def _on_login_requested(self, host: str, port: int, username: str, password: str) -> None:
        self.login_page.set_busy(True)
        request = LoginRequest(username=username, password=password)
        if self.client.is_connected and (self.client.host, self.client.port) == (host, port):
            self._send_login(request)
        else:
            self._pending_login = request
            self.client.connect_to(host, port)

    def _send_login(self, request: LoginRequest) -> None:
        self._login_msg_id = self.client.send(MsgType.LOGIN, request)

    def _on_connected(self) -> None:
        if self._pending_login is not None:
            self._send_login(self._pending_login)
            self._pending_login = None

    def _on_connection_error(self, message: str) -> None:
        self._pending_login = None
        self.login_page.set_busy(False)
        self.login_page.show_error(message)

    def _on_disconnected(self, reason: str) -> None:
        # TODO(P3): sınav sırasında otomatik yeniden bağlanma.
        self._pending_login = None
        self.login_page.set_busy(False)
        self.login_page.reset_password()
        self.login_page.show_error(f"{reason} Lütfen tekrar giriş yapın.")
        self.pages.setCurrentWidget(self.login_page)

    # --- Sunucudan gelen mesajlar ---

    def _on_message(self, envelope: Envelope) -> None:
        try:
            payload = parse_payload(envelope)
        except ProtocolError:
            logging.warning("Sunucudan hatalı mesaj: %s", envelope.type)
            return
        if envelope.type == MsgType.LOGIN_OK:
            assert isinstance(payload, LoginOk)
            self.login_page.set_busy(False)
            self.login_page.reset_password()
            self.waiting_page.show_user(payload.user)
            self.pages.setCurrentWidget(self.waiting_page)
        elif envelope.type == MsgType.ERROR and envelope.id == self._login_msg_id:
            assert isinstance(payload, ErrorPayload)
            self.login_page.set_busy(False)
            self.login_page.reset_password()
            self.login_page.show_error(payload.message)
        # TODO(P3): exam_start, save_ok, submit_ok, exam_end

    def closeEvent(self, event: QCloseEvent) -> None:
        self.client.close()
        if self._discovery is not None:
            self._discovery.wait()  # keşif en fazla birkaç saniye sürer
        event.accept()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("LabSınav Öğrenci")
    app.setStyleSheet(STYLESHEET)

    window = StudentWindow()
    window.show()
    window.start_discovery()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
