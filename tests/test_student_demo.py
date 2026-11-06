"""Demo modu ve sınav ekranının ekransız duman testleri."""

from tests.qt_utils import qapp, qt_wait_until  # önce gelmeli (offscreen)

from shared.protocol import SavedAnswer
from student_app.demo import DemoBackend, load_demo_exam
from student_app.main import StudentWindow, parse_args
from student_app.ui.exam_widgets import QuestionGrid
from student_app.net.server_clock import ServerClock


def test_demo_exam_json_is_valid_exam_start() -> None:
    start = load_demo_exam(30, ServerClock())
    assert start.exam.questions
    assert {q.type for q in start.exam.questions} >= {"mcq", "classic"}
    assert 1790 < (start.ends_at - start.server_now).total_seconds() <= 1800


def test_parse_args() -> None:
    args = parse_args(["--demo", "--demo-minutes", "6"])
    assert args.demo and args.demo_minutes == 6


def test_demo_flow_answer_save_and_submit(monkeypatch) -> None:
    qapp()
    backend = DemoBackend(30)
    window = StudentWindow(backend)
    backend.start()
    view = window.exam_view
    assert window.pages.currentWidget() is view
    assert view.state.is_answered(2)  # demo_exam.json'daki kayıtlı cevap

    view.go_to(3)
    view._pages[3].editor._edit.setPlainText("&")
    assert view.top_bar.save_label.text() == "Kaydediliyor…"
    view.flush_saves()
    qt_wait_until(lambda: not view.state.dirty)
    assert backend.saved[4].text_answer == "&"
    assert view.top_bar.save_label.text() == "Kaydedildi ✓"

    # Aynı exam_start tekrar gelirse ekran baştan kurulmaz, işaret ve konum korunur.
    view.state.toggle_mark(5)
    pages_before = list(view._pages)
    backend.exam_started.emit(backend._exam)
    assert view._pages == pages_before and view._current == 3 and view.state.marked == {5}

    monkeypatch.setattr(view, "_confirm_finish", lambda: True)
    view._on_finish_clicked()
    qt_wait_until(lambda: window.pages.currentWidget() is window.finished_page)
    assert window.finished_page.title_label.text().startswith("Sınavın gönderildi — ")
    backend.close()


def test_time_up_error_shows_finished_page() -> None:
    qapp()
    backend = DemoBackend(30)
    window = StudentWindow(backend)
    backend.start()
    window.exam_view.state.set_answer(4, SavedAnswer(text_answer="x"))
    backend.error_received.emit("TIME_UP", "Süre doldu.", "save_answer")
    assert window.pages.currentWidget() is window.finished_page
    assert "Süre doldu" in window.finished_page.detail_label.text()
    backend.close()


def test_grid_shows_answered_and_marked_separately() -> None:
    qapp()
    grid = QuestionGrid()
    grid.build(4)
    grid.set_status(0, answered=True, marked=True, current=False)
    grid.set_status(1, answered=False, marked=True, current=False)
    grid.set_status(2, answered=True, marked=False, current=False)
    grid.set_status(3, answered=False, marked=False, current=True)
    buttons = grid._buttons
    assert [b.property("status") for b in buttons] == ["answered_marked", "marked", "answered", "empty"]
    assert [b.flagged for b in buttons] == [True, False, False, False]  # bayrak sadece ilkinde
    assert buttons[0].toolTip() == "Soru 1: Cevaplandı, sonra bakacağım"
