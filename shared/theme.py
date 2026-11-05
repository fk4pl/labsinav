"""İki uygulamanın ortak görünümü (Qt Style Sheet).

Kullanım: app.setStyleSheet(STYLESHEET)
Özel görünüm için widget'a objectName ver: ör. QPushButton#secondary, QLabel#title.
"""

PRIMARY = "#2563eb"
PRIMARY_HOVER = "#1d4ed8"
DANGER = "#dc2626"
SUCCESS = "#16a34a"
BG = "#f5f7fb"
SURFACE = "#ffffff"
BORDER = "#d9dee8"
TEXT = "#1f2937"
MUTED = "#6b7280"

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

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {PRIMARY};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
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
