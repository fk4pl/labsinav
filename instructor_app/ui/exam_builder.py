"""Sınavlar sekmesi. (Sahibi: B — P5)"""

from PySide6.QtWidgets import QWidget

from instructor_app.ui.placeholder import PlaceholderPage


class ExamBuilderPage(PlaceholderPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Sınavlar", "Sınav oluşturma ve başlatma burada olacak.", parent)
