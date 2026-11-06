"""Eğitmen giriş penceresi, ilk kurulum penceresi ve şifre değiştirme penceresi. (Sahibi: B)

Uygulama açılınca önce LoginDialog gösterilir; sadece role='instructor' olan kullanıcı
girebilir. Giriş başarılı olunca dialog.user dolu olur ve ana pencere açılır.

Veri tabanında hiç eğitmen yoksa (ilk açılış) giriş yerine FirstSetupDialog açılır;
ilk eğitmen hesabı oluşturulunca normal giriş ekranına geçilir.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from server.db.models import User
from server.services.auth import (
    PasswordChangeError,
    SetupError,
    authenticate,
    change_password,
    create_first_instructor,
)
from server.services.event_log import Event, log_event

LOG_DETAIL = "eğitmen uygulaması"


def _password_input(placeholder: str) -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setMaxLength(128)
    return field


def _error_label() -> QLabel:
    label = QLabel()
    label.setObjectName("error")
    label.setWordWrap(True)
    label.hide()
    return label


class LoginDialog(QDialog):
    """Eğitmen girişi. exec() Accepted dönerse self.user giriş yapan eğitmendir."""

    def __init__(self, parent: QWidget | None = None, username: str = "") -> None:
        super().__init__(parent)
        self.user: User | None = None
        self.setWindowTitle("LabSınav — Eğitmen Girişi")
        self.setMinimumSize(480, 420)

        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(400)
        form = QVBoxLayout(card)
        form.setContentsMargins(32, 32, 32, 32)
        form.setSpacing(10)

        title = QLabel("LabSınav")
        title.setObjectName("title")
        subtitle = QLabel("Eğitmen girişi")
        subtitle.setObjectName("subtitle")
        form.addWidget(title)
        form.addWidget(subtitle)
        form.addSpacing(8)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Kullanıcı adı")
        self.username_input.setMaxLength(64)
        self.password_input = _password_input("Şifre")
        self.username_input.returnPressed.connect(self.password_input.setFocus)
        self.password_input.returnPressed.connect(self._submit)
        form.addWidget(self.username_input)
        form.addWidget(self.password_input)
        if username:  # ilk kurulumdan gelindiyse kullanıcı adı hazır yazılı olsun
            self.username_input.setText(username)
            self.password_input.setFocus()

        self.error_label = _error_label()
        form.addWidget(self.error_label)

        self.login_button = QPushButton("Giriş yap")
        self.login_button.setAutoDefault(False)
        self.login_button.clicked.connect(self._submit)
        form.addWidget(self.login_button)

        outer = QVBoxLayout(self)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _submit(self) -> None:
        self.error_label.hide()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self._show_error("Kullanıcı adı ve şifre boş bırakılamaz.")
            return

        user = authenticate(username, password)
        if user is None:
            log_event(Event.LOGIN_FAILED, username=username, detail=LOG_DETAIL)
            self._show_error("Kullanıcı adı veya şifre hatalı.")
            self.password_input.clear()
            self.password_input.setFocus()
            return
        if user.role != "instructor":
            log_event(Event.LOGIN_FAILED, username=username, detail=f"{LOG_DETAIL}: eğitmen değil")
            self._show_error("Bu uygulamaya sadece eğitmenler girebilir.")
            self.password_input.clear()
            return

        log_event(Event.LOGIN, username=username, detail=LOG_DETAIL)
        self.user = user
        self.accept()


class FirstSetupDialog(QDialog):
    """İlk kurulum: hiç eğitmen yokken ilk eğitmen hesabını oluşturur.

    exec() Accepted dönerse self.username oluşturulan hesabın kullanıcı adıdır.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.username: str | None = None
        self.setWindowTitle("LabSınav — İlk kurulum")
        self.setMinimumSize(480, 520)

        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(400)
        form = QVBoxLayout(card)
        form.setContentsMargins(32, 32, 32, 32)
        form.setSpacing(10)

        title = QLabel("İlk kurulum")
        title.setObjectName("title")
        info = QLabel("Henüz eğitmen hesabı yok. Bu bilgisayarda kullanılacak ilk eğitmen hesabını oluşturun.")
        info.setObjectName("subtitle")
        info.setWordWrap(True)
        form.addWidget(title)
        form.addWidget(info)
        form.addSpacing(8)

        self.full_name_input = QLineEdit()
        self.full_name_input.setPlaceholderText("Ad soyad")
        self.full_name_input.setMaxLength(100)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Kullanıcı adı")
        self.username_input.setMaxLength(64)
        self.password_input = _password_input("Şifre (en az 6 karakter)")
        self.repeat_input = _password_input("Şifre (tekrar)")
        self.repeat_input.returnPressed.connect(self._submit)
        for field in (self.full_name_input, self.username_input, self.password_input, self.repeat_input):
            form.addWidget(field)

        self.error_label = _error_label()
        form.addWidget(self.error_label)

        self.create_button = QPushButton("Hesabı oluştur")
        self.create_button.setAutoDefault(False)
        self.create_button.clicked.connect(self._submit)
        form.addWidget(self.create_button)

        note = QLabel("Deneme verisi için: python -m scripts.seed")
        note.setObjectName("subtitle")
        note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addWidget(note)

        outer = QVBoxLayout(self)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

    def _submit(self) -> None:
        self.error_label.hide()
        try:
            user = create_first_instructor(
                self.full_name_input.text(), self.username_input.text(),
                self.password_input.text(), self.repeat_input.text(),
            )
        except SetupError as error:
            self.error_label.setText(error.message)
            self.error_label.show()
            return
        self.username = user.username
        self.accept()


class ChangePasswordDialog(QDialog):
    """Giriş yapmış eğitmenin şifresini değiştirir (Ayarlar → Şifre değiştir)."""

    def __init__(self, user_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.user_id = user_id
        self.setWindowTitle("Şifre değiştir")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        title = QLabel("Şifre değiştir")
        title.setObjectName("title")
        layout.addWidget(title)

        self.old_input = _password_input("Mevcut şifre")
        self.new_input = _password_input("Yeni şifre (en az 6 karakter)")
        self.repeat_input = _password_input("Yeni şifre (tekrar)")
        self.repeat_input.returnPressed.connect(self._submit)
        for field in (self.old_input, self.new_input, self.repeat_input):
            layout.addWidget(field)

        self.error_label = _error_label()
        layout.addWidget(self.error_label)

        save_button = QPushButton("Kaydet")
        save_button.setAutoDefault(False)
        save_button.clicked.connect(self._submit)
        cancel_button = QPushButton("Vazgeç")
        cancel_button.setObjectName("secondary")
        cancel_button.setAutoDefault(False)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(save_button)
        layout.addWidget(cancel_button)

    def _submit(self) -> None:
        self.error_label.hide()
        if self.new_input.text() != self.repeat_input.text():
            self._show_error("Yeni şifreler birbiriyle aynı değil.")
            return
        try:
            change_password(self.user_id, self.old_input.text(), self.new_input.text())
        except PasswordChangeError as error:
            self._show_error(error.message)
            return
        self.accept()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()
