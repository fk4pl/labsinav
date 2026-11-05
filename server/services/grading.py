"""Puanlama: mcq, classic ve code (FİNAL) sorularının puanlanması. (Sahibi: D — P4)

Şimdilik sadece boş bir taslak (stub). Sunucu, bir sınav gönderildiğinde
(öğrenci "Gönder"e bastığında, süre dolduğunda veya eğitmen sınavı durdurduğunda)
her submission için grade_submission() fonksiyonunu ayrı bir thread'de çağırır.

D için notlar:
- Veri tabanına yazarken server.db.session.write_session() kullan.
- Uzun sürecek işleri (gcc ile derleme vb.) write_session() bloğunun DIŞINDA yap.
- Hata fırlatırsan gönderim bozulmaz, sadece sunucu loguna yazılır.
"""


def grade_submission(submission_id: int) -> None:
    """Verilen submission'ın cevaplarını puanlar ve total_score'u yazar. (D yazacak)"""
    return None
