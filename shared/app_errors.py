"""İki uygulama için ortak: loglama ayarı ve yakalanmamış hataları yakalama.

Neden gerekli?
- Bir buton fonksiyonunda beklenmeyen bir hata (bug) olursa Qt bunu sadece konsola yazar;
  kullanıcı hiçbir şey görmez, eğitmen "program dondu" sanır.
- Paketlenmiş (PyInstaller) uygulamada konsol yoktur; hata hiçbir yere yazılmaz.

Bu modül:
1. Logları hem konsola hem logs/<uygulama>.log dosyasına yazar.
2. Yakalanmamış hatayı (traceback) log dosyasına yazar ve kullanıcıya ham traceback
   yerine anlaşılır Türkçe bir mesaj gösterir. Uygulama kapanmaz, çalışmaya devam eder.

Kullanım (main() başında, QApplication oluşturulduktan sonra):
    setup_logging("instructor")
    install_error_handler()
"""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from types import TracebackType

from shared import config

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_FILE_BYTES = 1_000_000  # 1 MB dolunca yeni dosyaya geçilir
LOG_FILE_COUNT = 3          # en fazla 3 eski dosya saklanır

ERROR_TITLE = "Beklenmeyen hata"
ERROR_TEXT = (
    "Beklenmeyen bir hata oluştu. Son işlem tamamlanmamış olabilir.\n\n"
    "Uygulama çalışmaya devam ediyor. Sorun tekrarlarsa uygulamayı yeniden başlatın ve "
    "logs klasöründeki {log_name} dosyasını geliştirici ekibe iletin."
)

_log_name = "uygulama.log"
_showing_error = False  # aynı anda üst üste hata pencereleri açılmasın


def setup_logging(app_name: str) -> None:
    """Logları konsola ve logs/<app_name>.log dosyasına yazar."""
    global _log_name
    _log_name = f"{app_name}.log"
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:  # paketlenmiş pencereli uygulamada stderr olmayabilir
        handlers.append(logging.StreamHandler())
    try:
        config.ensure_runtime_dirs()
        handlers.append(RotatingFileHandler(
            config.LOG_DIR / _log_name, maxBytes=LOG_FILE_BYTES,
            backupCount=LOG_FILE_COUNT, encoding="utf-8",
        ))
    except OSError:
        pass  # log klasörü yazılamıyorsa sadece konsola yazılır
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=handlers, force=True)


def install_error_handler() -> None:
    """Yakalanmamış hataları loglar ve kullanıcıya Türkçe mesaj gösterir."""
    sys.excepthook = handle_exception
    threading.excepthook = _handle_thread_exception


def handle_exception(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logger.error("Yakalanmamış hata", exc_info=(exc_type, exc, tb))
    _show_error_dialog()


def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
    # Arka plan thread'inde arayüz açılamaz; sadece loglanır.
    logger.error(
        "Thread'de yakalanmamış hata (%s)", args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _show_error_dialog() -> None:
    global _showing_error
    from PySide6.QtWidgets import QApplication, QMessageBox

    if _showing_error or QApplication.instance() is None:
        return
    if threading.current_thread() is not threading.main_thread():
        return  # Qt pencereleri sadece ana thread'den açılabilir
    _showing_error = True
    try:
        QMessageBox.critical(None, ERROR_TITLE, ERROR_TEXT.format(log_name=_log_name))
    finally:
        _showing_error = False
