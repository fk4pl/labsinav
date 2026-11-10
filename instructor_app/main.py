"""Eğitmen uygulaması: python -m instructor_app.main
(--smoke-test: paketleme kontrolü, geçici veri tabanıyla açılıp hemen çıkar)

Açılış sırası: veri tabanı hazırlanır → (hiç eğitmen yoksa) ilk kurulum penceresi →
eğitmen giriş penceresi → (giriş başarılıysa) WebSocket sunucusu ve keşif dinleyicisi
başlar → ana pencere açılır.
Giriş penceresi kapatılırsa sunucu hiç açılmadan uygulama biter.
"""

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget

from instructor_app.server_bridge import ServerBridge
from instructor_app.ui.data_menu import DataMenu
from instructor_app.ui.exam_builder import ExamBuilderPage
from instructor_app.ui.firewall_prompt import FirewallPrompt
from instructor_app.ui.live_panel import LivePanelPage
from instructor_app.ui.login import ChangePasswordDialog, FirstSetupDialog, LoginDialog
from instructor_app.ui.logs import LogsPage
from instructor_app.ui.question_bank import QuestionBankPage
from instructor_app.ui.results import ResultsPage
from instructor_app.ui.students import StudentsPage
from server.db.models import User
from server.db.session import configure as configure_db
from server.db.session import get_engine, init_db
from server.services.auth import has_instructor, hash_password
from server.net.discovery import DiscoveryResponder, get_local_ip
from server.net.ws_server import ConnectedStudent, WsServer, start_server
from server.services import exam_admin
from shared import config
from shared.app_errors import install_error_handler, setup_logging
from shared.python_check import warn_if_unsupported_python
from shared.theme import STYLESHEET

STATUS_UPDATE_MS = 250  # durum çubuğu (bağlı öğrenci sayısı) en fazla bu aralıkla yenilenir


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
        settings_menu.addSeparator()
        self.data_menu = DataMenu(self, server)
        self.data_menu.add_actions(settings_menu)
        self.firewall_prompt = FirewallPrompt(self)

        self.status_label = QLabel()
        self.statusBar().addWidget(QLabel(f"Eğitmen: {user.full_name}"))
        self.statusBar().addPermanentWidget(self.status_label)
        self.update_status()

        # 40 öğrenci aynı anda bağlanınca durum çubuğu 40 kez değil, bir kez yenilensin.
        self.status_timer = QTimer(self)
        self.status_timer.setSingleShot(True)
        self.status_timer.setInterval(STATUS_UPDATE_MS)
        self.status_timer.timeout.connect(self.update_status)
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
        if not self.status_timer.isActive():
            self.status_timer.start()

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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LabSınav eğitmen uygulaması")
    parser.add_argument("--smoke-test", action="store_true",
                        help="paketleme kontrolü: veri tabanını ve pencereyi deneyip hemen çık")
    args, _unknown = parser.parse_known_args(argv)  # Qt'nin kendi argümanlarını yoksay
    return args


def smoke_test() -> int:
    """Paketlenmiş .exe'nin açılabildiğini kontrol eder (GitHub Actions kullanır).

    Gerçek veri tabanına dokunmaz: geçici klasörde boş bir veri tabanı oluşturulur.
    Modüller, Qt eklentileri, SQLite ve bcrypt yüklenebiliyorsa 0 döner.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        configure_db(Path(temp_dir) / "smoke.db")
        init_db()
        has_instructor()
        hash_password("duman-testi")
        dialog = LoginDialog()
        dialog.deleteLater()
        get_engine().dispose()  # Windows: geçici dosya silinebilsin
    logging.info("Duman testi başarılı")
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging("instructor")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LabSınav Eğitmen")
    app.setStyleSheet(STYLESHEET)
    if args.smoke_test:
        return smoke_test()
    install_error_handler()
    warn_if_unsupported_python()

    config.ensure_runtime_dirs()
    init_db()

    username = ""
    if not has_instructor():
        # İlk açılış: önce eğitmen hesabı oluşturulur, sonra normal giriş ekranı gelir.
        setup = FirstSetupDialog()
        if not setup.exec() or setup.username is None:
            return 0
        username = setup.username
        QMessageBox.information(
            None, "LabSınav", "Eğitmen hesabı oluşturuldu. Şimdi şifrenizle giriş yapın."
        )

    login = LoginDialog(username=username)
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
    # Pencere ekrana geldikten sonra (Windows'ta) güvenlik duvarı kuralları kontrol edilir.
    QTimer.singleShot(0, window.firewall_prompt.check)
    exit_code = app.exec()

    if discovery is not None:
        discovery.stop()
    server.stop()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
