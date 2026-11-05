import json
from datetime import datetime, timezone

import pytest

from shared.protocol import (
    PAYLOAD_MODELS,
    ErrorCode,
    ExamStart,
    LoginRequest,
    MsgType,
    OptionForStudent,
    ProtocolError,
    QuestionForStudent,
    decode,
    encode,
    make_error,
    parse_payload,
)


def test_login_round_trip() -> None:
    raw = encode(MsgType.LOGIN, LoginRequest(username="260101001", password="x"), "a1b2")
    envelope = decode(raw)
    assert envelope.type == "login"
    assert envelope.id == "a1b2"
    payload = parse_payload(envelope)
    assert payload == LoginRequest(username="260101001", password="x")


def test_envelope_json_shape() -> None:
    data = json.loads(encode(MsgType.PING, None, "z9"))
    assert data == {"type": "ping", "id": "z9", "payload": {}}


def test_exam_start_round_trip_with_datetimes_and_int_keys() -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
    original = ExamStart.model_validate({
        "exam": {"id": 1, "title": "Deneme", "questions": [
            {"id": 7, "type": "mcq", "text": "Soru?", "points": 10, "order_index": 0,
             "options": [{"id": 1, "text": "A", "order_index": 0}]},
        ]},
        "ends_at": now, "server_now": now,
        "saved_answers": {7: {"selected_option_id": 1}},
    })
    parsed = parse_payload(decode(encode(MsgType.EXAM_START, original)))
    assert parsed == original
    assert 7 in parsed.saved_answers  # JSON'da "7" string'i olsa da int'e geri döner


def test_make_error() -> None:
    envelope = decode(make_error(ErrorCode.INVALID_CREDENTIALS, "Hatalı", "id1"))
    payload = parse_payload(envelope)
    assert envelope.type == MsgType.ERROR
    assert payload.code == ErrorCode.INVALID_CREDENTIALS
    assert payload.message == "Hatalı"


@pytest.mark.parametrize("raw", ["bu json değil", "[1, 2]", '{"id": "x"}', b"\xff\xfe"])
def test_decode_rejects_malformed(raw: str | bytes) -> None:
    with pytest.raises(ProtocolError) as exc:
        decode(raw)
    assert exc.value.code == ErrorCode.BAD_REQUEST


def test_decode_rejects_unknown_type() -> None:
    with pytest.raises(ProtocolError) as exc:
        decode('{"type": "hack", "payload": {}}')
    assert exc.value.code == ErrorCode.UNKNOWN_TYPE


def test_parse_payload_rejects_missing_field() -> None:
    with pytest.raises(ProtocolError) as exc:
        parse_payload(decode('{"type": "login", "payload": {"username": "a"}}'))
    assert exc.value.code == ErrorCode.BAD_REQUEST


def test_encode_rejects_unknown_type() -> None:
    with pytest.raises(ValueError):
        encode("bilinmeyen")


def test_student_models_have_no_answer_key_fields() -> None:
    forbidden = {"is_correct", "accepted_answers", "answer", "test_cases", "expected_output", "is_hidden"}
    assert forbidden.isdisjoint(OptionForStudent.model_fields)
    assert forbidden.isdisjoint(QuestionForStudent.model_fields)


def test_student_models_reject_answer_key_even_if_passed() -> None:
    with pytest.raises(Exception):
        OptionForStudent(id=1, text="A", order_index=0, is_correct=True)


def test_every_message_type_has_model() -> None:
    names = {v for k, v in vars(MsgType).items() if not k.startswith("_")}
    assert names == set(PAYLOAD_MODELS)
