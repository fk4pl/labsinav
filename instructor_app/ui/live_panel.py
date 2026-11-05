"""Canlı Panel sekmesi. (Sahibi: B — P5)"""

from PySide6.QtWidgets import QWidget

from instructor_app.ui.placeholder import PlaceholderPage


class LivePanelPage(PlaceholderPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Canlı Panel", "Sınav sırasında öğrencilerin durumu burada izlenecek.", parent)
