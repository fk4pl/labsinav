"""Cevapların öğrenci bilgisayarındaki yedeği (JSON dosyası). (Sahibi: C)

Neden: bağlantı koparsa ya da uygulama çökerse/kapatılırsa öğrencinin yazdıkları kaybolmasın.
Her cevap değişikliğinde dosya baştan yazılır (birkaç KB, hızlıdır).

Dosya yeri: işletim sisteminin kullanıcı uygulama veri klasörü (platformdirs), ör.
    Windows: C:\\Users\\<ad>\\AppData\\Local\\LabSinav\\backups\\260101001_3.json
    Linux:   ~/.local/share/LabSinav/backups/260101001_3.json

Çökmeye dayanıklı yazma: önce "<dosya>.tmp" yazılır, sonra os.replace ile asıl dosyanın
yerine konur. os.replace tek adımdır; yazma yarıda kesilse bile eski dosya sağlam kalır.

Bu modül Qt kullanmaz; pytest ile kolayca test edilir.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs
from pydantic import ValidationError

from shared.protocol import SavedAnswer

logger = logging.getLogger(__name__)

BACKUP_VERSION = 1


def default_backup_dir() -> Path:
    return Path(platformdirs.user_data_dir("LabSinav", appauthor=False)) / "backups"


@dataclass
class BackupData:
    """Yedekten okunan veriler. answers içindeki her SavedAnswer'ın updated_at'i doludur."""

    answers: dict[int, SavedAnswer] = field(default_factory=dict)
    marked: set[int] = field(default_factory=set)


class LocalBackup:
    def __init__(self, directory: Path, username: str, exam_id: int) -> None:
        self.username = username
        self.exam_id = exam_id
        self.path = directory / f"{_safe_name(username)}_{exam_id}.json"

    def save(self, answers: dict[int, SavedAnswer], marked: set[int]) -> None:
        """Yedeği yazar. Disk hatasında OSError fırlar (çağıran yakalar)."""
        data = {
            "version": BACKUP_VERSION,
            "username": self.username,
            "exam_id": self.exam_id,
            "marked": sorted(marked),
            "answers": {str(qid): a.model_dump(mode="json") for qid, a in answers.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, self.path)

    def load(self) -> BackupData | None:
        """Yedeği okur. Dosya yoksa ya da bozuksa None döner (uygulama çökmez)."""
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("username") != self.username or data.get("exam_id") != self.exam_id:
                return None
            answers = {
                int(qid): SavedAnswer.model_validate(value)
                for qid, value in data.get("answers", {}).items()
            }
            marked = {int(qid) for qid in data.get("marked", [])}
        except (OSError, ValueError, TypeError, AttributeError, ValidationError):
            logger.warning("Yerel yedek okunamadı: %s", self.path, exc_info=True)
            return None
        return BackupData(answers={q: a for q, a in answers.items() if a.updated_at}, marked=marked)

    def delete(self) -> None:
        """Sınav gönderildi: yedeğe artık gerek yok."""
        for path in (self.path, self.path.with_suffix(".json.tmp")):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Yerel yedek silinemedi: %s", path, exc_info=True)


def _safe_name(username: str) -> str:
    """Kullanıcı adını dosya adında güvenle kullanılabilir hale getirir (öğrenci no zaten rakamdır)."""
    return "".join(ch if ch.isalnum() else "_" for ch in username)
