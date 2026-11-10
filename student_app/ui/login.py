"""Öğrenci giriş ekranı. (Sahibi: C)

Üstte sunucu durumu gösterilir. Sunucu otomatik bulunamazsa IP girme alanı açılır;
bu sırada main.py sunucuyu birkaç saniyede bir kendiliğinden aramaya devam eder.
Ekran sadece kullanıcıdan bilgi toplar; ağ işlerini student_app/main.py yapar.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shared import config


def parse_address(text: str) -> tuple[str, int] | None:
    """'192.168.1.10' veya '192.168.1.10:8765' biçimini (ip, port)'a çevirir."""
    text = text.strip()
    if not text:
        return None
    host, sep, port_text = text.rpartition(":")
    if not sep:
        return text, config.WS_PORT
    if not host or not port_text.isdigit() or not 0 < int(port_text) < 65536:
        return None
    return host, int(port_text)


class LoginPage(QWidget):
    # (host, port, kullanıcı adı, şifre)
    login_requested = Signal(str, int, str, str)
    rediscover_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._server: tuple[str, int] | None = None

        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(400)
        form = QVBoxLayout(card)
        form.setContentsMargins(32, 32, 32, 32)
        form.setSpacing(10)

        title = QLabel("LabSınav")
        title.setObjectName("title")
        subtitle = QLabel("Öğrenci girişi")
        subtitle.setObjectName("subtitle")
        form.addWidget(title)
        form.addWidget(subtitle)
        form.addSpacing(8)

        # Sunucu durumu + elle adres girme
        self.server_label = QLabel()
        self.server_label.setObjectName("subtitle")
        self.server_label.setWordWrap(True)
        form.addWidget(self.server_label)

        self.address_row = QWidget()
        address_layout = QHBoxLayout(self.address_row)
        address_layout.setContentsMargins(0, 0, 0, 0)
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Sunucu IP (ör. 192.168.1.10)")
        self.retry_button = QPushButton("Tekrar ara")
        self.retry_button.setObjectName("secondary")
        self.retry_button.clicked.connect(self.rediscover_requested)
        address_layout.addWidget(self.address_input)
        address_layout.addWidget(self.retry_button)
        form.addWidget(self.address_row)
        form.addSpacing(8)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Öğrenci numarası")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Şifre")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.username_input.setMaxLength(64)   # protocol.LoginRequest sınırları
        self.password_input.setMaxLength(128)
        self.username_input.returnPressed.connect(self.password_input.setFocus)
        self.password_input.returnPressed.connect(self._submit)
        form.addWidget(self.username_input)
        form.addWidget(self.password_input)

        self.error_label = QLabel()
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        form.addWidget(self.error_label)

        self.login_button = QPushButton("Giriş yap")
        self.login_button.clicked.connect(self._submit)
        form.addWidget(self.login_button)

        outer = QVBoxLayout(self)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        self.set_searching()

    # --- Sunucu durumu ---

    def set_searching(self) -> None:
        self._server = None
        self.server_label.setText("Sunucu aranıyor…")
        self.address_row.hide()
        self.retry_button.setEnabled(False)

    def has_server(self) -> bool:
        return self._server is not None

    def set_server_found(self, host: str, port: int) -> None:
        self._server = (host, port)
        self.server_label.setText(f"Sunucu bulundu: {host}:{port}")
        self.address_row.hide()
        if not self.password_input.hasFocus():  # şifre yazılıyorsa imleci oradan alma
            self.username_input.setFocus()

    def set_address_hint(self, host: str, port: int) -> None:
        """Son bağlanılan sunucu: IP kutusuna önceden yazılır (öğrenci tekrar yazmasın)."""
        if self.address_input.text():
            return
        text = host if port == config.WS_PORT else f"{host}:{port}"
        self.address_input.setText(text)

    def set_server_not_found(self) -> None:
        self._server = None
        self.server_label.setText(
            "Sunucu bulunamadı, otomatik olarak tekrar aranıyor… "
            "İsterseniz eğitmen bilgisayarının IP adresini girin."
        )
        self.retry_button.setEnabled(True)
        if self.address_row.isHidden():
            # Sadece ilk seferde: her tekrar aramada imleci öğrencinin elinden alma.
            self.address_row.show()
            self.address_input.setFocus()

    # --- Giriş ---

    def set_busy(self, busy: bool) -> None:
        self.login_button.setEnabled(not busy)
        self.login_button.setText("Giriş yapılıyor…" if busy else "Giriş yap")

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def clear_error(self) -> None:
        self.error_label.hide()

    def reset_password(self) -> None:
        self.password_input.clear()

    def _submit(self) -> None:
        self.clear_error()
        server = self._server
        if self.address_row.isVisible():
            server = parse_address(self.address_input.text())
            if server is None:
                self.show_error("Geçerli bir sunucu IP adresi girin.")
                return
        if server is None:
            self.show_error("Sunucu henüz bulunamadı, lütfen bekleyin.")
            return
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self.show_error("Öğrenci numarası ve şifre boş bırakılamaz.")
            return
        self.login_requested.emit(server[0], server[1], username, password)
