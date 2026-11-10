"""--smoke-test: paketlenmiş .exe'nin GitHub Actions'taki duman testiyle aynı kontrol."""

from tests.qt_utils import qapp  # önce gelmeli (offscreen)

import logging
from pathlib import Path

import pytest

from instructor_app import main as instructor_main
from shared import config
from student_app import main as student_main


@pytest.fixture
def restore_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """main() loglamayı yeniden ayarlar: loglar geçici klasöre yazılsın, sonra eski hâline dönsün."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers, root.level = handlers, level


def test_instructor_smoke_test(empty_db: Path, restore_logging) -> None:
    qapp()
    assert instructor_main.main(["--smoke-test"]) == 0


def test_student_smoke_test(restore_logging) -> None:
    qapp()
    assert student_main.main(["--smoke-test"]) == 0
