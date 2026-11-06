"""Sınav ekranının verisi: cevaplar, işaretler, kaydedilmemiş değişiklikler. (Sahibi: C)

Bu sınıf Qt kullanmaz; böylece pytest ile kolayca test edilir.
Ekran (ui/exam_view.py) sadece bu sınıfı günceller ve ondan okur.

"dirty" (kirli) cevap: öğrencinin değiştirdiği ama sunucunun henüz save_ok ile
onaylamadığı cevap. Bağlantı koparsa bu cevaplar kaybolmaz; yeniden bağlanınca tekrar gönderilir.

Her cevap updated_at taşır (sunucu saatine göre, UTC). Uygulama çöküp tekrar açılınca yerel
yedek (local_backup.py) ile sunucudaki cevaplar merge_backup() ile birleştirilir: hangisi daha yeniyse o kazanır.
"""

from datetime import datetime

from shared.protocol import ExamForStudent, ExamStart, QuestionForStudent, SavedAnswer
from student_app.local_backup import BackupData


def is_filled(answer: SavedAnswer | None) -> bool:
    """Cevap boş değil mi? (sunucudaki exam_session._is_filled ile aynı kural)"""
    if answer is None:
        return False
    return (
        answer.selected_option_id is not None
        or bool((answer.text_answer or "").strip())
        or bool((answer.code or "").strip())
    )


class ExamState:
    def __init__(self) -> None:
        self.exam: ExamForStudent | None = None
        self.questions: list[QuestionForStudent] = []
        self.answers: dict[int, SavedAnswer] = {}
        self.marked: set[int] = set()   # "sonra bakacağım" işaretli soru id'leri
        self.dirty: set[int] = set()    # sunucuya henüz onaylatılmamış soru id'leri
        # Her değişiklikte artan sayaç. save_ok geldiğinde, gönderdiğimiz sürüm hâlâ
        # en son sürümse soru "kaydedildi" sayılır; arada yeniden değiştiyse kirli kalır.
        self._version: dict[int, int] = {}
        self._sent_version: dict[int, int] = {}

    @property
    def exam_id(self) -> int | None:
        return self.exam.id if self.exam else None

    def load(self, start: ExamStart) -> bool:
        """exam_start'ı yükler. Aynı sınav tekrar geldiyse True döner (ekran baştan kurulmasın).

        Aynı sınav: sunucudaki kayıtlı cevaplar alınır, ama yerelde kaydedilmemiş (dirty)
        cevaplar daha yeni olduğu için korunur. İşaretler de korunur.
        """
        same_exam = self.exam is not None and self.exam.id == start.exam.id
        if not same_exam:
            self.answers, self.marked, self.dirty = {}, set(), set()
            self._version, self._sent_version = {}, {}
        self.exam = start.exam
        self.questions = sorted(start.exam.questions, key=lambda q: q.order_index)
        question_ids = {q.id for q in self.questions}
        for qid, saved in start.saved_answers.items():
            if qid in question_ids and qid not in self.dirty:
                self.answers[qid] = saved
        # Gönderilmiş ama onayı gelmemiş istekler bağlantıyla birlikte kayboldu: tekrar gönderilecek.
        self._sent_version = {}
        return same_exam

    # --- Cevaplar ---

    def answer_for(self, question_id: int) -> SavedAnswer | None:
        return self.answers.get(question_id)

    def set_answer(self, question_id: int, answer: SavedAnswer, at: datetime | None = None) -> None:
        """Öğrenci cevabı değiştirdi. at: değişikliğin zamanı (sunucu saatine göre)."""
        self.answers[question_id] = answer.model_copy(update={"updated_at": at})
        self.dirty.add(question_id)
        self._version[question_id] = self._version.get(question_id, 0) + 1

    def is_answered(self, question_id: int) -> bool:
        return is_filled(self.answers.get(question_id))

    def take_unsent(self) -> list[int]:
        """Gönderilmesi gereken soru id'leri (kirli ve bu sürümü henüz gönderilmemiş)."""
        unsent = [
            qid for qid in sorted(self.dirty)
            if self._sent_version.get(qid) != self._version.get(qid)
        ]
        for qid in unsent:
            self._sent_version[qid] = self._version.get(qid, 0)
        return unsent

    def mark_saved(self, question_id: int) -> None:
        """save_ok geldi. Gönderilen sürüm en son sürümse soru artık kirli değil."""
        if self._sent_version.get(question_id) == self._version.get(question_id):
            self.dirty.discard(question_id)

    def forget_sent(self) -> None:
        """Bağlantı koptu: onayı beklenen istekler kayboldu, tekrar gönderilecekler."""
        self._sent_version = {}

    def merge_backup(self, backup: BackupData) -> int:
        """Yerel yedeği sunucudan gelen cevaplarla birleştirir. Yedekten alınan cevap sayısını döner.

        Yedekteki cevap şu durumlarda kazanır ve tekrar gönderilmek üzere kirli işaretlenir:
          - sunucuda bu sorunun cevabı yoksa,
          - sunucudakinin zamanı bilinmiyorsa veya yedektekinden eskiyse.
        Sunucudaki cevap daha yeniyse (ör. öğrenci başka bilgisayardan devam etti) sunucu kazanır.
        """
        question_ids = {q.id for q in self.questions}
        taken = 0
        for qid, local in backup.answers.items():
            if qid not in question_ids or local.updated_at is None:
                continue
            server = self.answers.get(qid)
            if server is not None and server.updated_at is not None and server.updated_at >= local.updated_at:
                continue
            if server is not None and _same_content(server, local):
                continue  # aynı cevap zaten sunucuda: tekrar göndermeye gerek yok
            self.set_answer(qid, local, local.updated_at)
            taken += 1
        self.marked |= backup.marked & question_ids
        return taken

    # --- İşaretler ve özet ---

    def toggle_mark(self, question_id: int) -> bool:
        """İşareti açar/kapatır; yeni durumu döner."""
        if question_id in self.marked:
            self.marked.discard(question_id)
            return False
        self.marked.add(question_id)
        return True

    def unanswered_numbers(self) -> list[int]:
        """Cevaplanmamış soruların ekrandaki numaraları (1'den başlar)."""
        return [i + 1 for i, q in enumerate(self.questions) if not self.is_answered(q.id)]

    def marked_numbers(self) -> list[int]:
        return [i + 1 for i, q in enumerate(self.questions) if q.id in self.marked]


def _same_content(a: SavedAnswer, b: SavedAnswer) -> bool:
    return (a.selected_option_id, a.text_answer, a.code) == (b.selected_option_id, b.text_answer, b.code)
