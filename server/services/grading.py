"""Puanlama: mcq ve classic soruların puanlanması, elle puan verme. (Sahibi: D — P4)

Sunucu, bir sınav gönderildiğinde (öğrenci "Gönder"e bastığında, süre dolduğunda veya
eğitmen sınavı durdurduğunda) her submission için grade_submission() fonksiyonunu ayrı
bir thread'de çağırır. Hata fırlatırsak gönderim bozulmaz, sadece sunucu loguna yazılır.

Kurallar (CLAUDE.md → Puanlama):
- mcq: seçilen şık doğruysa sorunun puanı, değilse 0.
- classic: cevap normalize edilir, kabul edilen cevaplardan biriyle eşleşirse tam puan.
- code: FİNAL'de yazılacak; şimdilik puanlanmaz (points_awarded = None).
- Sorunun puanı exam_questions.points'ten gelir (sorunun varsayılan puanından değil).
- Eğitmenin elle verdiği puan (answers.is_manual = True) otomatik puanlamada KORUNUR.

Boş bırakılan soru için answers satırı hiç olmayabilir; bu durumda puan 0 sayılır.
"""

import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.db.models import Answer, ExamQuestion, Question, Submission
from server.db.session import get_session, write_session
from server.services.question_bank import turkish_lower

# Cevabın sonundaki bu işaretler yok sayılır ("İstanbul." == "istanbul")
TRAILING_PUNCTUATION = ".,;:!?…"

# Puanı elle değiştirilebilen soru tipleri (mcq her zaman otomatik puanlanır)
MANUAL_TYPES = {"classic", "code"}


class GradingError(Exception):
    """Puanlama kuralı ihlal edildi. message: kullanıcıya gösterilebilir Türkçe açıklama."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Cevap karşılaştırma
# ---------------------------------------------------------------------------

def normalize_answer(text: str | None) -> str:
    """Klasik cevabı karşılaştırmaya hazırlar.

    '  İSTANBUL.  ' → 'istanbul',  'Bağlı   Liste' → 'bağlı liste'
    """
    if not text:
        return ""
    # Aynı harf iki farklı şekilde kodlanabilir (ör. 'İ' tek karakter ya da 'I' + nokta);
    # NFC hepsini tek biçime getirir.
    text = unicodedata.normalize("NFC", text)
    text = turkish_lower(text)
    text = " ".join(text.split())  # baş/son boşluklar + çoklu boşluk, sekme, satır sonu
    return text.rstrip(TRAILING_PUNCTUATION).rstrip()


def is_answer_correct(question: Question, answer: Answer) -> bool | None:
    """Cevap doğru mu? Otomatik puanlanamayan sorularda (code) None döner."""
    if question.type == "mcq":
        return any(o.id == answer.selected_option_id and o.is_correct for o in question.options)
    if question.type == "classic":
        given = normalize_answer(answer.text_answer)
        accepted = {normalize_answer(a.answer) for a in question.accepted_answers}
        return given != "" and given in accepted
    return None  # code: FİNAL


# ---------------------------------------------------------------------------
# Puanlama
# ---------------------------------------------------------------------------

def grade_submission(submission_id: int) -> None:
    """Gönderilmiş bir sınavın cevaplarını puanlar ve total_score'u yazar.

    Aynı submission için birden çok kez çağrılabilir; sonuç hep aynı olur.
    Elle puanlanmış cevaplara dokunulmaz.
    """
    with write_session() as session:
        submission = session.get(Submission, submission_id)
        if submission is None:
            raise GradingError("Gönderim bulunamadı.")
        if submission.status != "submitted":
            raise GradingError("Öğrenci sınavı henüz göndermedi; puanlanamaz.")
        points = _question_points(session, submission.exam_id)
        for answer in submission.answers:
            if not answer.is_manual:
                _grade_answer(answer, points.get(answer.question_id, 0.0))
        submission.total_score = _total_score(submission)


def _grade_answer(answer: Answer, full_points: float) -> None:
    """Tek cevabı otomatik puanlar (is_correct ve points_awarded alanlarını yazar)."""
    correct = is_answer_correct(answer.question, answer)
    answer.is_correct = correct
    if correct is None:
        answer.points_awarded = None  # henüz puanlanamıyor (code)
    else:
        answer.points_awarded = full_points if correct else 0.0


def regrade_exam(exam_id: int) -> int:
    """Sınavın gönderilmiş tüm kâğıtlarını yeniden puanlar. Kaç kâğıt puanlandığını döner.

    Her kâğıt ayrı bir yazma işleminde puanlanır; böylece kilit uzun süre tutulmaz.
    Elle verilmiş puanlar korunur.
    """
    with get_session() as session:
        submission_ids = list(session.scalars(
            select(Submission.id).where(
                Submission.exam_id == exam_id, Submission.status == "submitted"
            )
        ))
    for submission_id in submission_ids:
        grade_submission(submission_id)
    return len(submission_ids)


def ungraded_submission_ids() -> list[int]:
    """Gönderilmiş ama hiç puanlanmamış (total_score boş) kâğıtlar.

    Sunucu açılışta bunları puanlar: uygulama, gönderimden hemen sonra (puanlama
    bitmeden) kapanmış veya çökmüş olabilir.
    """
    with get_session() as session:
        return list(session.scalars(
            select(Submission.id)
            .where(Submission.status == "submitted", Submission.total_score.is_(None))
            .order_by(Submission.id)
        ))


# ---------------------------------------------------------------------------
# Elle puan
# ---------------------------------------------------------------------------

def set_manual_points(answer_id: int, points: float) -> float:
    """Eğitmen bir cevaba elle puan verir. Kâğıdın yeni toplam puanını döner.

    Puan 0 ile sorunun sınavdaki puanı arasında olmalı. Tam puan verilirse cevap
    'doğru' sayılır; kısmi puan 'yanlış' sayılır ama puanı korunur.
    """
    with write_session() as session:
        answer, full_points = _get_editable_answer(session, answer_id)
        if not 0 <= points <= full_points:  # NaN da bu kontrolden geçemez
            raise GradingError(f"Puan 0 ile {full_points:g} arasında olmalı.")
        answer.points_awarded = points
        answer.is_correct = points >= full_points
        answer.is_manual = True
        submission = answer.submission
        submission.total_score = _total_score(submission)
        return submission.total_score


def clear_manual_points(answer_id: int) -> float:
    """Elle verilen puanı geri alır, cevabı tekrar otomatik puanlar. Yeni toplamı döner."""
    with write_session() as session:
        answer, full_points = _get_editable_answer(session, answer_id)
        answer.is_manual = False
        _grade_answer(answer, full_points)
        submission = answer.submission
        submission.total_score = _total_score(submission)
        return submission.total_score


def _get_editable_answer(session: Session, answer_id: int) -> tuple[Answer, float]:
    """Elle puanlanabilecek cevabı ve sorunun tam puanını getirir; uygun değilse hata fırlatır."""
    answer = session.get(Answer, answer_id)
    if answer is None:
        raise GradingError("Cevap bulunamadı.")
    if answer.submission.status != "submitted":
        raise GradingError("Öğrenci sınavı henüz göndermedi; puan daha sonra verilebilir.")
    if answer.question.type not in MANUAL_TYPES:
        raise GradingError("Test sorularının puanı elle değiştirilemez.")
    points = _question_points(session, answer.submission.exam_id)
    return answer, points.get(answer.question_id, 0.0)


# ---------------------------------------------------------------------------
# Küçük yardımcılar
# ---------------------------------------------------------------------------

def _question_points(session: Session, exam_id: int) -> dict[int, float]:
    """{soru id: sınavdaki puanı}"""
    rows = session.execute(
        select(ExamQuestion.question_id, ExamQuestion.points).where(ExamQuestion.exam_id == exam_id)
    )
    return {question_id: points for question_id, points in rows}


def _total_score(submission: Submission) -> float:
    return sum(a.points_awarded or 0.0 for a in submission.answers)
