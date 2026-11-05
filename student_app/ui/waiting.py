"""Giriş sonrası bekleme ekranı. (Sahibi: C)"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from shared.protocol import UserInfo
from student_app.net.client import ConnectionState
from student_app.ui.style import repolish


class WaitingPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(460)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(12)

        self.greeting_label = QLabel()
        self.greeting_label.setObjectName("title")
        self.greeting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label = QLabel("Sınavın başlaması bekleniyor…")
        self.info_label.setObjectName("subtitle")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_label = QLabel()
        self.details_label.setObjectName("subtitle")
        self.details_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_label = QLabel("● Sunucuya bağlı")
        self.connection_label.setObjectName("success")
        self.connection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.greeting_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.details_label)
        layout.addSpacing(12)
        layout.addWidget(self.connection_label)

        outer = QVBoxLayout(self)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

    def show_user(self, user: UserInfo) -> None:
        self.greeting_label.setText(f"Merhaba {user.full_name}")
        details = user.username
        if user.class_name:
            details += f"  •  {user.class_name}"
        self.details_label.setText(details)

    def set_connection_state(self, state: str) -> None:
        if state == ConnectionState.CONNECTED:
            text, name = "● Sunucuya bağlı", "success"
        elif state == ConnectionState.RECONNECTING:
            text, name = "● Bağlantı koptu, yeniden bağlanıyor…", "error"
        else:
            text, name = "● Sunucuya bağlı değil", "error"
        self.connection_label.setText(text)
        self.connection_label.setObjectName(name)
        repolish(self.connection_label)
