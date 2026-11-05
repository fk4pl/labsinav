"""Soru Bankası sekmesi. (Sahibi: B — P2)"""

from PySide6.QtWidgets import QWidget

from instructor_app.ui.placeholder import PlaceholderPage


class QuestionBankPage(PlaceholderPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Soru Bankası", "Soru ekleme, düzenleme ve kategoriler burada olacak.", parent)
