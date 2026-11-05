"""Sonuçlar sekmesi. (Sahibi: D — P4)"""

from PySide6.QtWidgets import QWidget

from instructor_app.ui.placeholder import PlaceholderPage


class ResultsPage(PlaceholderPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Sonuçlar", "Puanlar, elle puan düzeltme ve Excel'e aktarma burada olacak.", parent)
