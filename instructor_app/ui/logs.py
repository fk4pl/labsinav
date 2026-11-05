"""Loglar sekmesi. (Sahibi: B — P5)"""

from PySide6.QtWidgets import QWidget

from instructor_app.ui.placeholder import PlaceholderPage


class LogsPage(PlaceholderPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Loglar", "Giriş, gönderim ve pencere değiştirme olayları burada filtrelenecek.", parent)
