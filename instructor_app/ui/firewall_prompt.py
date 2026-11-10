"""İlk açılışta güvenlik duvarı uyarısı (sadece Windows). (Sahibi: B)

Eğitmen giriş yaptıktan sonra main.py check() çağırır. Kurallar varsa (veya Linux'taysak)
hiçbir şey gösterilmez. Eksikse kullanıcıya kuralları yönetici olarak eklemesi önerilir.
UAC penceresi ayrı bir işlemde açıldığı için kuralların eklenip eklenmediği birkaç saniye
boyunca birer saniye arayla tekrar kontrol edilir.
"""

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox, QWidget

from instructor_app.firewall import add_rule_command, add_rules_elevated, missing_rules

RECHECK_INTERVAL_MS = 1000
RECHECK_TRIES = 30  # en fazla 30 sn bekle (UAC onayı için)

WARNING_TEXT = (
    "Windows güvenlik duvarında LabSınav için izin kuralı bulunamadı.\n\n"
    "Kural olmazsa öğrenci bilgisayarları sunucuyu bulamayabilir veya bağlanamayabilir.\n"
    "Kuralları şimdi eklemek ister misiniz? (Windows yönetici izni isteyecek.)"
)


class FirewallPrompt(QObject):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._tries_left = 0
        self._timer = QTimer(self)
        self._timer.setInterval(RECHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._recheck)

    def check(self) -> None:
        missing = missing_rules()
        if not missing:
            return
        box = QMessageBox(QMessageBox.Icon.Warning, "Güvenlik duvarı", WARNING_TEXT,
                          parent=self._parent)
        box.setDetailedText(
            "Yönetici olarak açılmış PowerShell'de elle de çalıştırabilirsiniz:\n\n"
            + "\n".join(add_rule_command(rule) for rule in missing)
        )
        add_button = box.addButton("Kuralları ekle (yönetici)", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Şimdi değil", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not add_button:
            return
        if add_rules_elevated(missing):
            self._tries_left = RECHECK_TRIES
            self._timer.start()
        else:
            QMessageBox.warning(
                self._parent, "Güvenlik duvarı",
                "Yönetici izni verilmedi, kurallar eklenmedi.\n"
                "Uygulama bir sonraki açılışta tekrar soracak.",
            )

    def _recheck(self) -> None:
        self._tries_left -= 1
        if not missing_rules():
            self._timer.stop()
            QMessageBox.information(
                self._parent, "Güvenlik duvarı",
                "Güvenlik duvarı kuralları eklendi. Öğrenciler artık bağlanabilir.",
            )
        elif self._tries_left <= 0:
            self._timer.stop()
            QMessageBox.warning(
                self._parent, "Güvenlik duvarı",
                "Kuralların eklendiği doğrulanamadı. Ayrıntılar için docs/SORUN_GIDERME.md'ye bakın.",
            )
