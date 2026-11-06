"""Eğitmen giriş ve ilk kurulum pencereleri (offscreen Qt)."""

from tests.qt_utils import qapp  # QT_QPA_PLATFORM'u ayarlar; önce gelmeli

from instructor_app.ui.login import FirstSetupDialog, LoginDialog
from server.services.auth import authenticate, has_instructor


def fill(dialog: FirstSetupDialog, full_name: str, username: str, password: str, again: str) -> None:
    dialog.full_name_input.setText(full_name)
    dialog.username_input.setText(username)
    dialog.password_input.setText(password)
    dialog.repeat_input.setText(again)


def test_first_setup_shows_error_for_invalid_input(empty_db) -> None:
    qapp()
    dialog = FirstSetupDialog()
    fill(dialog, "Ayşe Korkmaz", "ayse", "gizli123", "baska123")
    dialog._submit()
    assert not dialog.error_label.isHidden()
    assert "aynı değil" in dialog.error_label.text()
    assert dialog.result() != FirstSetupDialog.DialogCode.Accepted
    assert not has_instructor()


def test_first_setup_creates_instructor_and_accepts(empty_db) -> None:
    qapp()
    dialog = FirstSetupDialog()
    fill(dialog, "Ayşe Korkmaz", "ayse", "gizli123", "gizli123")
    dialog._submit()
    assert dialog.result() == FirstSetupDialog.DialogCode.Accepted
    assert dialog.username == "ayse"
    assert authenticate("ayse", "gizli123").role == "instructor"


def test_first_setup_shows_seed_hint(empty_db) -> None:
    qapp()
    from PySide6.QtWidgets import QLabel

    dialog = FirstSetupDialog()
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert "Deneme verisi için: python -m scripts.seed" in texts


def test_login_dialog_prefills_username(empty_db) -> None:
    qapp()
    dialog = LoginDialog(username="ayse")
    assert dialog.username_input.text() == "ayse"
