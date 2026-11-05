"""Öğrenciler sekmesi. (Sahibi: D — P6)"""

from PySide6.QtWidgets import QWidget

from instructor_app.ui.placeholder import PlaceholderPage


class StudentsPage(PlaceholderPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Öğrenciler", "Öğrenci listesi ve Excel'den içe aktarma burada olacak.", parent)
