"""Ayarlar menüsündeki veri işlemleri. (Sahibi: B)

- Veri klasörünü aç: veri tabanının ve logların bulunduğu klasörü dosya gezgininde açar.
- Veri tabanını yedekle…: tarihli bir kopya kaydeder (server/services/backup.py).
- Örnek veri yükle (deneme): python -m scripts.seed'in yaptığını yapar; .exe sürümünde
  Python olmadan demo verisi yüklenebilsin diye. Mevcut TÜM veriyi siler, önce onay ister.
  Giriş yapmış eğitmen hesabı da silindiği için iş bitince uygulama kapanır.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QProgressDialog, QWidget

from scripts.seed import INSTRUCTOR, load_demo_data
from server.net.ws_server import WsServer
from server.services import exam_admin
from server.services.backup import backup_database, default_backup_name
from shared import config

logger = logging.getLogger(__name__)

SEED_CONFIRM_TEXT = (
    "Örnek veri yüklenince veri tabanındaki TÜM veriler (sorular, sınavlar, öğrenciler, "
    "sonuçlar, eğitmen hesapları) SİLİNİR ve yerine deneme verisi konur.\n\n"
    "Önemli verileriniz varsa önce \"Veri tabanını yedekle…\" ile yedek alın.\n\n"
    "Devam edilsin mi?"
)


class SeedThread(QThread):
    """Örnek veriyi arka planda yükler (şifre hash'leri birkaç saniye sürer)."""

    succeeded = Signal()
    failed = Signal()

    def run(self) -> None:
        try:
            load_demo_data()
        except Exception:
            logger.exception("Örnek veri yüklenemedi")
            self.failed.emit()
        else:
            self.succeeded.emit()


class DataMenu(QObject):
    def __init__(self, parent: QWidget, server: WsServer) -> None:
        super().__init__(parent)
        self._parent = parent
        self._server = server
        self._seed_thread: SeedThread | None = None
        self._progress: QProgressDialog | None = None

    def add_actions(self, menu: QMenu) -> None:
        menu.addAction("Veri klasörünü aç", self.open_data_folder)
        menu.addAction("Veri tabanını yedekle…", self.backup)
        menu.addSeparator()
        menu.addAction("Örnek veri yükle (deneme)", self.load_demo_data)

    # --- Veri klasörü ---

    def open_data_folder(self) -> None:
        config.ensure_runtime_dirs()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.DATA_DIR))):
            QMessageBox.information(self._parent, "Veri klasörü", f"Veri klasörü:\n{config.DATA_DIR}")

    # --- Yedek ---

    def backup(self) -> None:
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        suggested = Path(documents or Path.home()) / default_backup_name(datetime.now())
        path, _filter = QFileDialog.getSaveFileName(
            self._parent, "Veri tabanını yedekle", str(suggested), "Veri tabanı (*.db)",
        )
        if not path:
            return
        try:
            backup_database(Path(path))
        except (OSError, sqlite3.Error):
            logger.exception("Yedek alınamadı")
            QMessageBox.critical(
                self._parent, "Yedek alınamadı",
                "Yedek dosyası yazılamadı. Başka bir klasör seçip tekrar deneyin.",
            )
            return
        QMessageBox.information(self._parent, "Yedek alındı", f"Yedek kaydedildi:\n{path}")

    # --- Örnek veri ---

    def load_demo_data(self) -> None:
        reason = self._seed_blocked_reason()
        if reason is not None:
            QMessageBox.warning(self._parent, "Örnek veri yüklenemez", reason)
            return
        answer = QMessageBox.warning(
            self._parent, "Örnek veri yükle", SEED_CONFIRM_TEXT,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,  # Enter'a yanlışlıkla basılırsa silinmesin
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._progress = QProgressDialog("Örnek veri yükleniyor…", "", 0, 0, self._parent)
        self._progress.setWindowTitle("Örnek veri")
        self._progress.setCancelButton(None)  # yarıda kesilemez
        self._progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._progress.show()
        self._seed_thread = SeedThread(self)
        self._seed_thread.succeeded.connect(self._on_seed_succeeded)
        self._seed_thread.failed.connect(self._on_seed_failed)
        self._seed_thread.start()

    def _seed_blocked_reason(self) -> str | None:
        if exam_admin.list_running_exams():
            return "Devam eden bir sınav var. Örnek veri sınav bittikten sonra yüklenebilir."
        if self._server.connected_students():
            return "Bağlı öğrenciler var. Örnek veri yüklemeden önce öğrenci uygulamalarını kapatın."
        return None

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None

    def _on_seed_succeeded(self) -> None:
        self._close_progress()
        QMessageBox.information(
            self._parent, "Örnek veri yüklendi",
            "Örnek veri yüklendi. Uygulama şimdi kapanacak.\n\n"
            f"Yeniden açıp {INSTRUCTOR[0]} / {INSTRUCTOR[1]} ile giriş yapın.\n"
            "Öğrenciler: 260101001 … 260101030, şifre = öğrenci no.",
        )
        QApplication.quit()

    def _on_seed_failed(self) -> None:
        self._close_progress()
        QMessageBox.critical(
            self._parent, "Örnek veri yüklenemedi",
            "Örnek veri yüklenirken bir hata oluştu. Ayrıntı logs klasöründeki instructor.log dosyasında.",
        )
