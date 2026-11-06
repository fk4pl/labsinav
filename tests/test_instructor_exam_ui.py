"""Eğitmen arayüzü duman testleri: Sınavlar, sınav düzenleme, Canlı Panel, Loglar.

Gerçek sunucu yerine FakeServer kullanılır; sinyaller elle yayılır (aynı thread'de
olduğu için slot hemen çalışır). Ekran gerekmez (offscreen).
"""

from tests.qt_utils import qapp, qt_wait_until  # QT_QPA_PLATFORM'u ayarlar; önce gelmeli

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from instructor_app.server_bridge import ServerBridge
from instructor_app.ui import live_panel
from instructor_app.ui.exam_builder import ExamBuilderPage
from instructor_app.ui.exam_editor_dialog import ExamEditorDialog
from instructor_app.ui.live_panel import IN_EXAM, OFFLINE, SUBMITTED, LivePanelPage
from instructor_app.ui.logs import LogsPage
from instructor_app.ui.question_bank import ROW_ROLE
from scripts.seed import DRAFT_EXAM_TITLE
from server.db.models import Exam, User, utcnow
from server.db.session import get_session
from server.net.ws_server import ConnectedStudent
from server.services import exam_admin, exam_session
from server.services.event_log import Event, log_event


class FakeServer:
    """WsServer'ın arayüzün kullandığı kısmı."""

    def __init__(self) -> None:
        self.online: list[ConnectedStudent] = []
        self.started: list[int] = []
        self.extended: list[tuple[int, int]] = []

    def connected_students(self) -> list[ConnectedStudent]:
        return list(self.online)

    def start_exam(self, exam_id: int) -> datetime:
        return exam_session.start_exam(exam_id, utcnow()).ends_at

    def extend_exam(self, exam_id: int, minutes: int) -> datetime:
        self.extended.append((exam_id, minutes))
        return exam_session.extend_exam(exam_id, minutes, utcnow()).ends_at

    def stop_exam(self, exam_id: int) -> None:
        exam_session.stop_exam(exam_id, utcnow())


def seeded_exam_id() -> int:
    with get_session() as session:
        return session.scalar(select(Exam.id).where(Exam.title == DRAFT_EXAM_TITLE))


def online_student(username: str) -> ConnectedStudent:
    with get_session() as session:
        user = session.scalar(select(User).where(User.username == username))
        return ConnectedStudent(
            user_id=user.id, username=user.username, full_name=user.full_name,
            class_id=user.class_id, class_name=None, ip="10.0.0.5", connected_at=utcnow(),
        )


@pytest.fixture
def instructor(seeded_db) -> User:
    qapp()
    with get_session() as session:
        return session.scalar(select(User).where(User.role == "instructor"))


# ---------------------------------------------------------------------------
# Sınav düzenleme penceresi
# ---------------------------------------------------------------------------

def test_editor_add_move_and_save(instructor: User) -> None:
    dialog = ExamEditorDialog(None, instructor.id)
    dialog.title_input.setText("Quiz")
    dialog.class_combo.setCurrentIndex(1)

    dialog.bank_table.selectRow(0)
    dialog._add_selected()
    dialog.bank_table.selectRow(0)  # ilk eklenen bankadan gizlendi; sıradaki soru
    dialog._add_selected()
    first, second = dialog.question_ids()
    assert dialog.total_points() == 20
    assert "20 puan · 2 soru" in dialog.total_label.text()
    bank_ids = {dialog.bank_proxy.index(r, 0).data(ROW_ROLE).id for r in range(dialog.bank_proxy.rowCount())}
    assert first not in bank_ids  # sınava eklenen soru bankada gizlenir

    dialog.exam_table.selectRow(1)
    dialog._move_up()
    assert dialog.question_ids() == [second, first]

    dialog._save()
    assert dialog.saved_id is not None
    detail = exam_admin.get_exam(dialog.saved_id)
    assert [q.question_id for q in detail.questions] == [second, first]


def test_editor_shows_errors_and_does_not_save(instructor: User) -> None:
    dialog = ExamEditorDialog(None, instructor.id)
    dialog._save()
    assert dialog.saved_id is None
    assert not dialog.error_box.isHidden()


def test_editor_read_only_mode(instructor: User) -> None:
    exam_id = seeded_exam_id()
    dialog = ExamEditorDialog(exam_id, instructor.id, read_only=True)
    assert len(dialog.question_ids()) == 10
    assert dialog.save_button.isHidden()
    assert not dialog.title_input.isEnabled()


# ---------------------------------------------------------------------------
# Sınavlar sekmesi
# ---------------------------------------------------------------------------

def test_builder_start_emits_signal(instructor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    page = ExamBuilderPage(FakeServer(), instructor)
    monkeypatch.setattr(page, "_confirm_start", lambda row: True)
    started: list[int] = []
    page.exam_started.connect(started.append)

    page.table.selectRow(0)
    assert page.start_button.isEnabled()
    page._start()

    assert started == [seeded_exam_id()]
    assert exam_admin.get_exam(started[0]).row.status == "running"
    assert not page.start_button.isEnabled()   # artık taslak değil
    assert page.open_button.text() == "Görüntüle"


# ---------------------------------------------------------------------------
# Canlı Panel
# ---------------------------------------------------------------------------

def test_live_panel_updates_from_signals(instructor: User) -> None:
    exam_id = seeded_exam_id()
    server, bridge = FakeServer(), ServerBridge()
    exam_session.start_exam(exam_id, utcnow())
    panel = LivePanelPage(server, bridge)
    assert panel.snapshot is not None and panel.snapshot.exam_id == exam_id
    assert panel.table.rowCount() == 15
    assert panel.status_of("260101001") == OFFLINE
    assert panel.counter_labels[OFFLINE].text() == "15"

    student = online_student("260101001")
    server.online.append(student)
    bridge.on_student_connected(student)
    assert panel.status_of("260101001") == IN_EXAM

    bridge.on_answer_saved(student, exam_id, 3)
    bridge.on_focus_lost(student, exam_id)
    row = panel.rows["260101001"]
    # Toplu güncelleme: tablo hemen değil, zamanlayıcı dolunca yenilenir.
    assert panel.table.item(row, live_panel.COL_ANSWERED).text() == "0 / 10"
    assert panel.flush_timer.isActive()
    panel.flush_pending()
    assert panel.table.item(row, live_panel.COL_ANSWERED).text() == "3 / 10"
    assert panel.table.item(row, live_panel.COL_FOCUS).text() == "1"
    assert panel.table.item(row, live_panel.COL_IP).text() == "10.0.0.5"

    bridge.on_submitted("260101001", exam_id, False)
    assert panel.status_of("260101001") == SUBMITTED
    panel.flush_pending()
    assert panel.counter_labels[SUBMITTED].text() == "1"
    assert panel.counter_labels[OFFLINE].text() == "14"

    bridge.on_answer_saved(student, exam_id + 999, 9)  # başka sınavın olayı yok sayılır
    panel.flush_pending()
    assert panel.table.item(row, live_panel.COL_ANSWERED).text() == "3 / 10"


def test_live_panel_extend_and_stop(instructor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    exam_id = seeded_exam_id()
    server, bridge = FakeServer(), ServerBridge()
    exam_session.start_exam(exam_id, utcnow())
    panel = LivePanelPage(server, bridge)
    old_end = panel.ends_at

    panel._extend_5()
    assert server.extended == [(exam_id, 5)]
    assert panel.ends_at == old_end + timedelta(minutes=5)

    monkeypatch.setattr(
        live_panel.QMessageBox, "question",
        staticmethod(lambda *args, **kwargs: live_panel.QMessageBox.StandardButton.Yes),
    )
    panel._stop()
    assert panel.snapshot.status == "finished"
    assert not panel.stop_button.isEnabled()
    assert panel.countdown_label.text() == "Bitti"


def test_live_panel_without_running_exam(instructor: User) -> None:
    panel = LivePanelPage(FakeServer(), ServerBridge())
    assert panel.snapshot is None
    assert panel.title_label.text() == "Devam eden sınav yok"
    assert not panel.extend5_button.isEnabled()


# ---------------------------------------------------------------------------
# Loglar
# ---------------------------------------------------------------------------

def test_logs_page_filters(instructor: User) -> None:
    log_event(Event.LOGIN, username="260101001")
    log_event(Event.LOGIN_FAILED, username="260101002")
    page = LogsPage()
    page.show()  # showEvent seçenekleri doldurur ve listeyi çeker
    assert page.table.rowCount() == 2

    page.event_filter.setCurrentIndex(page.event_filter.findData(Event.LOGIN_FAILED))
    assert page.table.rowCount() == 1
    assert page.table.item(0, 2).text() == "260101002 · Elif Kaya"  # no · ad soyad
    assert page.table.item(0, 4).text() == "—"  # boş IP
    page.close()


# ---------------------------------------------------------------------------
# Gerçek sunucu ile: sinyaller sunucu thread'inden UI thread'ine geliyor mu?
# ---------------------------------------------------------------------------

def test_live_panel_with_real_server(instructor: User) -> None:
    import json

    from websockets.sync.client import connect

    from server.net.ws_server import WsServer

    bridge = ServerBridge()
    server = WsServer(observer=bridge, host="127.0.0.1", port=0)
    server.start()
    try:
        exam_id = seeded_exam_id()
        panel = LivePanelPage(server, bridge)
        server.start_exam(exam_id)
        panel.show_exam(exam_id)

        with connect(f"ws://127.0.0.1:{server.port}") as ws:
            ws.send(json.dumps({"type": "login", "id": "1",
                                "payload": {"username": "260101001", "password": "260101001"}}))
            qt_wait_until(lambda: panel.status_of("260101001") == IN_EXAM)
            ws.send(json.dumps({"type": "focus_lost", "id": "2",
                                "payload": {"exam_id": exam_id, "at": utcnow().isoformat()}}))
            row = panel.rows["260101001"]
            qt_wait_until(lambda: panel.table.item(row, live_panel.COL_FOCUS).text() == "1")
            ws.send(json.dumps({"type": "submit", "id": "3", "payload": {"exam_id": exam_id}}))
            qt_wait_until(lambda: panel.status_of("260101001") == SUBMITTED)
        qt_wait_until(lambda: panel.counter_labels[SUBMITTED].text() == "1")
    finally:
        server.stop()


def test_live_panel_batches_many_signals(instructor: User) -> None:
    """Çok sayıda sinyal tek bir toplu güncellemeyle tabloya yansır."""
    exam_id = seeded_exam_id()
    server, bridge = FakeServer(), ServerBridge()
    exam_session.start_exam(exam_id, utcnow())
    panel = LivePanelPage(server, bridge)
    student = online_student("260101001")
    server.online.append(student)
    bridge.on_student_connected(student)
    for count in range(1, 101):
        bridge.on_answer_saved(student, exam_id, count % 11)
    assert panel.dirty == {"260101001"}
    qt_wait_until(lambda: not panel.dirty)  # zamanlayıcı kendiliğinden boşaltır
    row = panel.rows["260101001"]
    assert panel.table.item(row, live_panel.COL_ANSWERED).text() == "1 / 10"
    assert panel.counter_labels[IN_EXAM].text() == "1"


# ---------------------------------------------------------------------------
# Puan sınırları arayüzde
# ---------------------------------------------------------------------------

def test_points_spin_boxes_use_config_limits(instructor: User) -> None:
    from instructor_app.ui.exam_editor_dialog import COL_POINTS
    from instructor_app.ui.question_dialog import QuestionDialog
    from shared import config

    question_dialog = QuestionDialog([])
    assert question_dialog.points_spin.minimum() == config.MIN_QUESTION_POINTS
    assert question_dialog.points_spin.maximum() == config.MAX_QUESTION_POINTS

    editor = ExamEditorDialog(None, instructor.id)
    delegate = editor.exam_table.itemDelegateForColumn(COL_POINTS) or editor.exam_table.itemDelegate()
    spin = delegate.createEditor(editor.exam_table, None, editor.exam_table.model().index(0, 0))
    assert (spin.minimum(), spin.maximum()) == (config.MIN_QUESTION_POINTS, config.MAX_QUESTION_POINTS)


def test_editor_clamps_old_out_of_range_default_points(
    instructor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sınır konmadan önce 150 puanla kaydedilmiş soru sınava 100 puanla eklenir ve kullanıcı uyarılır."""
    from dataclasses import replace

    from instructor_app.ui import exam_editor_dialog

    shown: list[str] = []
    monkeypatch.setattr(
        exam_editor_dialog.QMessageBox, "information",
        staticmethod(lambda _parent, _title, text: shown.append(text)),
    )
    editor = ExamEditorDialog(None, instructor.id)
    row = next(iter(editor.bank_rows.values()))
    editor._add_rows([replace(row, default_points=150)])
    assert editor.points() == [100]
    assert shown and "sınıra çekildi" in shown[0]
