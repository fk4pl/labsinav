"""Henüz yazılmamış sekmeler için geçici sayfa."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPage(QWidget):
    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel(title)
        title_label.setObjectName("title")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        desc_label = QLabel(description)
        desc_label.setObjectName("placeholder")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(desc_label)
