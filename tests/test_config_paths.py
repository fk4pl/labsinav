"""Veri/log klasörleri: geliştirirken repo içi, .exe'de kullanıcının uygulama veri klasörü."""

from pathlib import Path

import platformdirs

from shared import config


def test_development_mode_uses_repo_folders() -> None:
    data_dir, log_dir = config.runtime_dirs(frozen=False)
    assert data_dir == config.BASE_DIR / "data"
    assert log_dir == config.BASE_DIR / "logs"


def test_frozen_mode_uses_user_data_dir() -> None:
    data_dir, log_dir = config.runtime_dirs(frozen=True)
    user_dir = Path(platformdirs.user_data_dir("LabSinav", appauthor=False))
    assert data_dir == user_dir / "data"
    assert log_dir == user_dir / "logs"


def test_tests_run_in_development_mode() -> None:
    assert not config.IS_FROZEN
    assert config.DB_PATH == config.BASE_DIR / "data" / "labsinav.db"
