"""İki uygulamanın ortak görünümü (Qt Style Sheet).

Kullanım: app.setStyleSheet(STYLESHEET)
Özel görünüm için widget'a objectName ver: ör. QPushButton#secondary, QLabel#title.
"""

from pathlib import Path

# Stil dosyasında kullanılan küçük resimler (spin kutusu okları). Qt yolda "/" bekler.
ASSETS = (Path(__file__).resolve().parent / "assets").as_posix()

PRIMARY = "#2563eb"
PRIMARY_HOVER = "#1d4ed8"
DANGER = "#dc2626"
SUCCESS = "#16a34a"
BG = "#f5f7fb"
SURFACE = "#ffffff"
BORDER = "#d9dee8"
TEXT = "#1f2937"
MUTED = "#6b7280"

# Kod parçaları için eşit genişlikli yazı tipi (ilk bulunan kullanılır)
MONO_FONT_FAMILY = '"Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New", monospace'

STYLESHEET = f"""
QWidget {{
    font-family: "Segoe UI", "Noto Sans", "Ubuntu", sans-serif;
    font-size: 14px;
    color: {TEXT};
}}
QMainWindow, QStackedWidget, QDialog {{
    background: {BG};
}}

/* Kart: içerik kutusu */
QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QLabel#title {{
    font-size: 22px;
    font-weight: 600;
}}
QLabel#subtitle {{
    font-size: 14px;
    color: {MUTED};
}}
QLabel#error {{
    color: {DANGER};
}}
QLabel#success {{
    color: {SUCCESS};
}}
QLabel#placeholder {{
    color: {MUTED};
    font-size: 16px;
}}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {PRIMARY};
}}

/* Spin kutusu: sağda iki ok butonu için yer ayrılır, oklar shared/assets/ içindeki SVG'ler. */
QSpinBox, QDoubleSpinBox {{
    padding: 6px 10px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    width: 24px;
    background: #f3f5f9;
    border: none;
    border-left: 1px solid {BORDER};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right;
    margin: 1px 1px 0 0;          /* dış kenarlığın üstüne binmesin */
    border-top-right-radius: 7px;
    border-bottom: 1px solid {BORDER};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right;
    margin: 0 1px 1px 0;
    border-bottom-right-radius: 7px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: #e4e9f2;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({ASSETS}/arrow_up.svg);
    width: 10px;
    height: 7px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({ASSETS}/arrow_down.svg);
    width: 10px;
    height: 7px;
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled,
QSpinBox::up-arrow:off, QDoubleSpinBox::up-arrow:off {{
    image: url({ASSETS}/arrow_up_disabled.svg);
}}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled,
QSpinBox::down-arrow:off, QDoubleSpinBox::down-arrow:off {{
    image: url({ASSETS}/arrow_down_disabled.svg);
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QListWidget:focus {{
    border: 1px solid {PRIMARY};
}}

QPushButton {{
    background: {PRIMARY};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {PRIMARY_HOVER};
}}
QPushButton:disabled {{
    background: #9db4ee;
}}
QPushButton#secondary {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QPushButton#secondary:hover {{
    background: #eef2f9;
}}
QPushButton#secondary:disabled {{
    color: #b0b7c3;
    background: {SURFACE};
}}

QPushButton#danger {{
    background: {DANGER};
}}
QPushButton#danger:hover {{
    background: #b91c1c;
}}
QPushButton#danger:disabled {{
    background: #f0a8a8;
}}
QPushButton#link {{
    background: transparent;
    color: {PRIMARY};
    padding: 4px 6px;
}}
QPushButton#link:hover {{
    text-decoration: underline;
}}
QPushButton#link:disabled {{
    color: {MUTED};
}}

/* Uyarı şeridi (ör. düzenlenemeyen soru) */
QLabel#warning {{
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fcd34d;
    border-radius: 8px;
    padding: 8px 10px;
}}
QLabel#error[box="true"] {{
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 8px;
    padding: 8px 10px;
}}

QTableView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: #eef1f6;
    selection-background-color: #dbe7ff;
    selection-color: {TEXT};
    alternate-background-color: #f9fafc;
}}
QHeaderView::section {{
    background: #f1f4f9;
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px 6px;
    font-weight: 600;
}}
QListWidget::item {{
    padding: 4px 2px;
}}
QListWidget::item:selected {{
    background: #dbe7ff;
    color: {TEXT};
}}

QMenuBar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item {{
    padding: 6px 12px;
    background: transparent;
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background: #eef2f9;
    color: {TEXT};
}}
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
}}
QMenu::item {{
    padding: 6px 20px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {SURFACE};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {MUTED};
    padding: 10px 18px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {PRIMARY};
    border-bottom: 2px solid {PRIMARY};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
}}

QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
    color: {MUTED};
}}
QStatusBar QLabel {{
    color: {MUTED};
    padding: 2px 8px;
}}
"""
