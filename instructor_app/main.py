"""Eğitmen uygulaması: python -m instructor_app.main

Açılış sırası: veri tabanı hazırlanır → eğitmen giriş penceresi → (giriş başarılıysa)
WebSocket sunucusu ve keşif dinleyicisi başlar → ana pencere açılır.
Giriş penceresi kapatılırsa sunucu hiç açılmadan uygulama biter.
"""

import logging
import sys

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget

from instructor_app.server_bridge import ServerBridge
from instructor_app.ui.exam_builder import ExamBuilderPage
from instructor_app.ui.live_panel import LivePanelPage
from instructor_app.ui.login import ChangePasswordDialog, LoginDialog
from instructor_app.ui.logs import LogsPage
from instructor_app.ui.question_bank import QuestionBankPage
from instructor_app.ui.results import ResultsPage
from instructor_app.ui.students import StudentsPage
from server.db.models import User
from server.db.session import init_db
from server.net.discovery import DiscoveryResponder, get_local_ip
from server.net.ws_server import ConnectedStudent, WsServer, start_server
from server.services import exam_admin
from shared import config
from shared.theme import STYLESHEET


class MainWindow(QMainWindow):
    def __init__(self, server: WsServer, bridge: ServerBridge, user: User) -> None:
        super().__init__()
        self.server = server
        self.user = user
        self.setWindowTitle("LabSınav — Eğitmen")
        self.resize(1100, 720)

        self.exam_page = ExamBuilderPage(server, user)
        self.live_page = LivePanelPage(server, bridge)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(QuestionBankPage(), "Soru Bankası")
        self.tabs.addTab(self.exam_page, "Sınavlar")
        self.tabs.addTab(self.live_page, "Canlı Panel")
        self.tabs.addTab(ResultsPage(), "Sonuçlar")
        self.tabs.addTab(StudentsPage(), "Öğrenciler")
        self.tabs.addTab(LogsPage(), "Loglar")
        self.setCentralWidget(self.tabs)

        self.exam_page.exam_started.connect(self.on_exam_started)
        bridge.exam_finished.connect(self.on_exam_finished)

        settings_menu = self.menuBar().addMenu("Ayarlar")
        settings_menu.addAction("Şifre değiştir…", self.change_password)

        self.status_label = QLabel()
        self.statusBar().addWidget(QLabel(f"Eğitmen: {user.full_name}"))
        self.statusBar().addPermanentWidget(self.status_label)
        self.update_status()

        bridge.student_connected.connect(self.on_student_changed)
        bridge.student_disconnected.connect(self.on_student_changed)

    def change_password(self) -> None:
        dialog = ChangePasswordDialog(self.user.id, self)
        accepted = dialog.exec()
        dialog.deleteLater()
        if accepted:
            QMessageBox.information(self, "Şifre değiştirildi", "Yeni şifreniz kaydedildi.")

    def on_exam_started(self, exam_id: int) -> None:
        """Sınavlar sekmesinde sınav başlatılınca Canlı Panel'e geçilir."""
        self.live_page.show_exam(exam_id)
        self.tabs.setCurrentWidget(self.live_page)

    def on_exam_finished(self, exam_id: int, reason: str) -> None:
        self.exam_page.reload()  # durum sütunu "Bitti" olsun

    def on_student_changed(self, student: ConnectedStudent) -> None:
        self.update_status()

    def update_status(self) -> None:
        count = len(self.server.connected_students())
        self.status_label.setText(
            f"Sunucu: {get_local_ip()}:{self.server.port}  •  Bağlı öğrenci: {count}"
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        message = self._close_warning()
        if message is not None:
            answer = QMessageBox.warning(
                self, "Çıkış", message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,  # Enter'a yanlışlıkla basılırsa kapanmasın
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()

    def _close_warning(self) -> str | None:
        """Kapatmadan önce gösterilecek uyarı; uyarılacak bir şey yoksa None."""
        running = exam_admin.list_running_exams()
        if running:
            titles = "\n".join(f"• {exam.title} ({exam.class_name})" for exam in running)
            return (
                f"DEVAM EDEN SINAV VAR:\n{titles}\n\n"
                "Uygulamayı kapatırsanız öğrencilerin bağlantısı kopar ve cevap kaydedemezler.\n"
                "Süre işlemeye devam eder; uygulamayı yeniden açınca sınav kaldığı yerden sürer.\n\n"
                "Yine de kapatılsın mı?"
            )
        if self.server.connected_students():
            return (
                "Bağlı öğrenciler var. Uygulamayı kapatırsanız bağlantıları kopacak.\n"
                "Yine de kapatılsın mı?"
            )
        return None


def _show_fatal(message: str) -> None:
    QMessageBox.critical(None, "LabSınav", message)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("LabSınav Eğitmen")
    app.setStyleSheet(STYLESHEET)

    config.ensure_runtime_dirs()
    init_db()

    login = LoginDialog()
    if not login.exec() or login.user is None:
        return 0

    bridge = ServerBridge()
    try:
        server = start_server(observer=bridge)
    except OSError:
        _show_fatal(
            f"Sunucu {config.WS_PORT} numaralı portta başlatılamadı.\n"
            "Eğitmen uygulaması zaten açık olabilir; açık pencereyi kontrol edin."
        )
        return 1

    discovery: DiscoveryResponder | None = None
    try:
        discovery = DiscoveryResponder(ws_port=server.port)
        discovery.start()
    except OSError:
        # Keşif çalışmazsa öğrenciler IP'yi elle girebilir; uygulama yine açılır.
        logging.warning("Keşif portu (%s) açılamadı", config.DISCOVERY_PORT)

    window = MainWindow(server, bridge, login.user)
    window.show()
    exit_code = app.exec()

    if discovery is not None:
        discovery.stop()
    server.stop()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
