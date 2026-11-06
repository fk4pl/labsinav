from datetime import datetime, timezone

from shared.protocol import ExamForStudent, ExamStart, OptionForStudent, QuestionForStudent, SavedAnswer
from student_app.exam_state import ExamState, is_filled

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


def make_start(exam_id: int = 1, saved: dict[int, SavedAnswer] | None = None) -> ExamStart:
    questions = [
        QuestionForStudent(id=10, type="mcq", text="?", points=5, order_index=2,
                           options=[OptionForStudent(id=100, text="a", order_index=1)]),
        QuestionForStudent(id=20, type="classic", text="?", points=5, order_index=1),
        QuestionForStudent(id=30, type="classic", text="?", points=5, order_index=3),
    ]
    return ExamStart(
        exam=ExamForStudent(id=exam_id, title="Sınav", questions=questions),
        ends_at=NOW, server_now=NOW, saved_answers=saved or {},
    )


def test_questions_sorted_and_saved_answers_loaded() -> None:
    state = ExamState()
    state.load(make_start(saved={10: SavedAnswer(selected_option_id=100)}))
    assert [q.id for q in state.questions] == [20, 10, 30]
    assert state.is_answered(10)
    assert state.unanswered_numbers() == [1, 3]


def test_same_exam_again_keeps_unsaved_local_answers_and_marks() -> None:
    state = ExamState()
    assert state.load(make_start()) is False
    state.set_answer(20, SavedAnswer(text_answer="yerel"))
    state.toggle_mark(30)
    again = state.load(make_start(saved={20: SavedAnswer(text_answer="eski"),
                                         30: SavedAnswer(text_answer="sunucu")}))
    assert again is True
    assert state.answer_for(20).text_answer == "yerel"      # kaydedilmemiş yerel cevap kazanır
    assert state.answer_for(30).text_answer == "sunucu"     # diğerleri sunucudan gelir
    assert state.marked == {30}
    assert state.take_unsent() == [20]                      # yerel cevap tekrar gönderilecek


def test_other_exam_resets_everything() -> None:
    state = ExamState()
    state.load(make_start(exam_id=1))
    state.set_answer(20, SavedAnswer(text_answer="x"))
    state.toggle_mark(10)
    assert state.load(make_start(exam_id=2)) is False
    assert state.answers == {} and state.marked == set() and state.dirty == set()


def test_save_ok_for_old_version_keeps_answer_dirty() -> None:
    state = ExamState()
    state.load(make_start())
    state.set_answer(20, SavedAnswer(text_answer="a"))
    assert state.take_unsent() == [20]
    state.set_answer(20, SavedAnswer(text_answer="ab"))  # onay gelmeden yeniden değişti
    state.mark_saved(20)                                   # eski sürümün onayı
    assert 20 in state.dirty
    assert state.take_unsent() == [20]
    state.mark_saved(20)
    assert state.dirty == set()


def test_take_unsent_does_not_resend_until_connection_lost() -> None:
    state = ExamState()
    state.load(make_start())
    state.set_answer(20, SavedAnswer(text_answer="a"))
    assert state.take_unsent() == [20]
    assert state.take_unsent() == []
    state.forget_sent()
    assert state.take_unsent() == [20]


def test_marked_numbers_and_is_filled() -> None:
    state = ExamState()
    state.load(make_start())
    state.toggle_mark(10)
    assert state.marked_numbers() == [2]
    assert state.toggle_mark(10) is False
    assert not is_filled(SavedAnswer(text_answer="   "))
    assert is_filled(SavedAnswer(code="int x;"))


# ---------------------------------------------------------------------------
# Yerel yedekle birleştirme (merge_backup)
# ---------------------------------------------------------------------------

from datetime import timedelta  # noqa: E402

from student_app.local_backup import BackupData  # noqa: E402

EARLY = NOW - timedelta(minutes=5)
LATE = NOW + timedelta(minutes=5)


def _local(text: str, at: datetime) -> SavedAnswer:
    return SavedAnswer(text_answer=text, updated_at=at)


def test_merge_backup_newer_local_wins_and_becomes_dirty() -> None:
    state = ExamState()
    state.load(make_start(saved={20: _local("sunucu", EARLY)}))
    taken = state.merge_backup(BackupData(answers={20: _local("yerel", LATE)}))
    assert taken == 1
    assert state.answer_for(20).text_answer == "yerel"
    assert state.take_unsent() == [20]  # sunucuya tekrar gönderilecek


def test_merge_backup_newer_server_wins() -> None:
    """Öğrenci başka bilgisayardan devam ettiyse eski yedek sunucudakini ezmez."""
    state = ExamState()
    state.load(make_start(saved={20: _local("sunucu", LATE)}))
    assert state.merge_backup(BackupData(answers={20: _local("eski yedek", EARLY)})) == 0
    assert state.answer_for(20).text_answer == "sunucu"
    assert not state.dirty


def test_merge_backup_takes_answers_missing_on_server_and_marks() -> None:
    state = ExamState()
    state.load(make_start())
    backup = BackupData(answers={30: _local("hiç gitmemiş", EARLY)}, marked={10, 999})
    assert state.merge_backup(backup) == 1
    assert state.answer_for(30).text_answer == "hiç gitmemiş"
    assert state.marked == {10}  # sınavda olmayan soru işareti alınmaz


def test_merge_backup_skips_unknown_question_and_same_content() -> None:
    state = ExamState()
    state.load(make_start(saved={20: SavedAnswer(text_answer="aynı")}))  # zamanı bilinmiyor
    backup = BackupData(answers={999: _local("x", LATE), 20: _local("aynı", LATE)})
    assert state.merge_backup(backup) == 0
    assert not state.dirty


def test_set_answer_records_time() -> None:
    state = ExamState()
    state.load(make_start())
    state.set_answer(20, SavedAnswer(text_answer="a"), LATE)
    assert state.answer_for(20).updated_at == LATE
