"""Öğrenci uygulamasına özel görünüm. Ortak tema (shared/theme.py) üzerine eklenir. (Sahibi: C)

Renkleri widget içinde inline yazmak yerine burada objectName / property ile tanımlarız;
böylece yazı boyutu büyütülünce (ui/zoom.py) bu boyutlar da birlikte büyür.
"""

from shared import theme

WARNING = "#ea580c"   # turuncu: son 5 dakika, işaretli soru, yeniden bağlanıyor

STUDENT_CSS = f"""
QFrame#topBar {{
    background: {theme.SURFACE};
    border-bottom: 1px solid {theme.BORDER};
}}
QLabel#examTitle {{
    font-size: 18px;
    font-weight: 600;
}}
QLabel#countdown {{
    font-size: 30px;
    font-weight: 700;
    font-family: "Consolas", "DejaVu Sans Mono", monospace;
    padding: 0 12px;
}}
QLabel#countdown[level="warning"] {{ color: {WARNING}; }}
QLabel#countdown[level="danger"] {{ color: {theme.DANGER}; }}

QLabel#status[level="ok"] {{ color: {theme.SUCCESS}; }}
QLabel#status[level="busy"] {{ color: {theme.MUTED}; }}
QLabel#status[level="warning"] {{ color: {WARNING}; }}
QLabel#status[level="danger"] {{ color: {theme.DANGER}; }}

QLabel#banner {{
    padding: 10px 16px;
    font-weight: 600;
    color: white;
    background: {theme.PRIMARY};
}}
QLabel#banner[level="warning"] {{ background: {WARNING}; }}
QLabel#banner[level="danger"] {{ background: {theme.DANGER}; }}

QLabel#questionHeader {{
    font-size: 13px;
    color: {theme.MUTED};
    font-weight: 600;
}}
QLabel#questionText {{
    font-size: 16px;
}}
QRadioButton {{
    font-size: 15px;
    padding: 6px 0;
}}
QRadioButton#codeOption {{
    font-family: "Consolas", "DejaVu Sans Mono", monospace;
}}
QPlainTextEdit#codeEditor {{
    font-family: "Consolas", "DejaVu Sans Mono", monospace;
}}

QPushButton#questionNumber {{
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
    border-radius: 6px;
    background: {theme.SURFACE};
    color: {theme.TEXT};
    border: 2px solid {theme.BORDER};
}}
QPushButton#questionNumber[status="answered"] {{
    background: {theme.SUCCESS};
    color: white;
    border-color: {theme.SUCCESS};
}}
QPushButton#questionNumber[status="marked"] {{
    background: {WARNING};
    color: white;
    border-color: {WARNING};
}}
/* Kenarlık kalınlığı hep aynı (2px); sadece rengi değişir, böylece butonlar kaymaz. */
QPushButton#questionNumber[current="true"] {{
    border-color: {theme.PRIMARY};
    font-weight: 800;
}}
QPushButton#danger {{
    background: {theme.DANGER};
}}
QPushButton#danger:hover {{
    background: #b91c1c;
}}
QLabel#legend {{
    font-size: 12px;
    color: {theme.MUTED};
}}
"""

FULL_STYLESHEET = theme.STYLESHEET + STUDENT_CSS


def repolish(widget) -> None:  # noqa: ANN001 — her QWidget olabilir
    """Dinamik property (ör. level, status) değişince Qt stilini yeniden uygular."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
