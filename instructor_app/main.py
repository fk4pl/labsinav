"""Eğitmen uygulaması: python -m instructor_app.main

Açılışta veri tabanını hazırlar, WebSocket sunucusunu ve keşif dinleyicisini başlatır.
"""

import logging
import sys

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget

from instructor_app.server_bridge import ServerBridge
from instructor_app.ui.exam_builder import ExamBuilderPage
from instructor_app.ui.live_panel import LivePanelPage
from instructor_app.ui.logs import LogsPage
from instructor_app.ui.question_bank import QuestionBankPage
from instructor_app.ui.results import ResultsPage
from instructor_app.ui.students import StudentsPage
from server.db.session import init_db
from server.net.discovery import DiscoveryResponder, get_local_ip
from server.net.ws_server import ConnectedStudent, WsServer, start_server
from shared import config
from shared.theme import STYLESHEET


class MainWindow(QMainWindow):
    def __init__(self, server: WsServer, bridge: ServerBridge) -> None:
        super().__init__()
        self.server = server
        self.setWindowTitle("LabSınav — Eğitmen")
        self.resize(1100, 720)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(QuestionBankPage(), "Soru Bankası")
        tabs.addTab(ExamBuilderPage(), "Sınavlar")
        tabs.addTab(LivePanelPage(), "Canlı Panel")
        tabs.addTab(ResultsPage(), "Sonuçlar")
        tabs.addTab(StudentsPage(), "Öğrenciler")
        tabs.addTab(LogsPage(), "Loglar")
        self.setCentralWidget(tabs)

        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)
        self.update_status()

        bridge.student_connected.connect(self.on_student_changed)
        bridge.student_disconnected.connect(self.on_student_changed)

    def on_student_changed(self, student: ConnectedStudent) -> None:
        self.update_status()

    def update_status(self) -> None:
        count = len(self.server.connected_students())
        self.status_label.setText(
            f"Sunucu: {get_local_ip()}:{self.server.port}  •  Bağlı öğrenci: {count}"
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.server.connected_students():
            answer = QMessageBox.question(
                self, "Çıkış",
                "Bağlı öğrenciler var. Uygulamayı kapatırsanız bağlantıları kopacak.\n"
                "Yine de kapatılsın mı?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()


def _show_fatal(message: str) -> None:
    QMessageBox.critical(None, "LabSınav", message)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("LabSınav Eğitmen")
    app.setStyleSheet(STYLESHEET)

    config.ensure_runtime_dirs()
    init_db()

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

    window = MainWindow(server, bridge)
    window.show()
    exit_code = app.exec()

    if discovery is not None:
        discovery.stop()
    server.stop()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
