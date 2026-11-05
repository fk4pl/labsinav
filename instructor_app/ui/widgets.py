"""Eğitmen arayüzündeki ekranların ortak küçük yardımcıları. (Sahibi: B)"""

from datetime import datetime

from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from shared.theme import MONO_FONT_FAMILY


def set_monospace(widget: QWidget, enabled: bool) -> None:
    """Metin kutusunu eşit genişlikli yazı tipine geçirir (kod parçaları için).

    Tema (shared/theme.py) yazı tipini QSS ile belirlediği için setFont() işe yaramaz;
    bu yüzden widget'a kendi küçük stylesheet'i verilir.
    """
    widget.setStyleSheet(f"font-family: {MONO_FONT_FAMILY}; font-size: 13px;" if enabled else "")


def make_error_box() -> QLabel:
    """Kırmızı hata kutusu (başta gizli). Metni show_errors() ile doldurulur."""
    label = QLabel()
    label.setObjectName("error")
    label.setProperty("box", True)
    label.setWordWrap(True)
    label.hide()
    return label


def show_errors(label: QLabel, errors: list[str]) -> None:
    """Hata listesini madde madde gösterir; liste boşsa kutuyu gizler."""
    if not errors:
        label.hide()
        return
    label.setText("\n".join(f"• {e}" for e in errors))
    label.show()


def format_points(points: float) -> str:
    """10.0 → '10', 2.5 → '2,5' (Türkçe ondalık virgülü)."""
    return f"{points:g}".replace(".", ",")


def make_button(text: str, object_name: str = "") -> QPushButton:
    """Buton oluşturur. object_name: "secondary" (gri), "danger" (kırmızı) veya boş (mavi).

    autoDefault kapalı: diyaloglarda Enter'a basınca yanlışlıkla tıklanmasın.
    """
    button = QPushButton(text)
    button.setAutoDefault(False)
    if object_name:
        button.setObjectName(object_name)
    return button


def format_local(moment: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """UTC zamanı bilgisayarın yerel saatine çevirip yazar; None ise '—'."""
    if moment is None:
        return "—"
    return moment.astimezone().strftime(fmt)
