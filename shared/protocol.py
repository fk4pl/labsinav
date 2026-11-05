"""İstemci ile sunucu arasındaki mesaj formatı.

Her mesaj bir JSON zarfıdır (Envelope):
    {"type": "login", "id": "a1b2", "payload": {...}}

Her mesaj tipinin payload'u aşağıda bir pydantic modeliyle tanımlıdır.
Yeni mesaj tipi eklemek için: MsgType'a sabit ekle, payload modelini yaz,
PAYLOAD_MODELS sözlüğüne ekle.

ÖNEMLİ: İstemciye giden soru modelleri (QuestionForStudent, OptionForStudent)
cevap anahtarı (is_correct, kabul edilen cevaplar, gizli test case'ler) İÇERMEZ.

Bu dosyayı değiştirmek ekip onayı gerektirir (CLAUDE.md).
"""

import json
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class MsgType:
    """Mesaj tipleri. Kodda string yazmak yerine bu sabitleri kullan."""

    # İstemci -> Sunucu
    LOGIN = "login"
    SAVE_ANSWER = "save_answer"
    SUBMIT = "submit"
    FOCUS_LOST = "focus_lost"
    PING = "ping"
    # Sunucu -> İstemci
    LOGIN_OK = "login_ok"
    ERROR = "error"
    EXAM_START = "exam_start"
    SAVE_OK = "save_ok"
    SUBMIT_OK = "submit_ok"
    EXAM_END = "exam_end"
    PONG = "pong"


class ErrorCode:
    """error mesajındaki makine tarafından okunabilir kodlar."""

    BAD_REQUEST = "BAD_REQUEST"              # bozuk JSON / eksik alan
    UNKNOWN_TYPE = "UNKNOWN_TYPE"            # sunucunun tanımadığı mesaj tipi
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    NOT_STUDENT = "NOT_STUDENT"              # eğitmen hesabıyla öğrenci uygulamasına giriş
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"  # giriş yapmadan istek
    TIME_UP = "TIME_UP"                      # süre dolduktan sonra gelen istek
    INTERNAL = "INTERNAL"                    # beklenmeyen sunucu hatası


class ProtocolError(Exception):
    """Gelen mesaj çözülemediğinde fırlatılır. message Türkçedir."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Model(BaseModel):
    # Tanımsız alan gelirse hata ver: yanlışlıkla cevap anahtarı eklenmesini de engeller.
    model_config = ConfigDict(extra="forbid")


class Envelope(_Model):
    type: str
    id: str | None = None
    payload: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# İstemci -> Sunucu payload'ları
# ---------------------------------------------------------------------------

class LoginRequest(_Model):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SaveAnswerRequest(_Model):
    exam_id: int
    question_id: int
    selected_option_id: int | None = None
    text_answer: str | None = Field(default=None, max_length=10_000)
    code: str | None = Field(default=None, max_length=100_000)


class SubmitRequest(_Model):
    exam_id: int


class FocusLostRequest(_Model):
    exam_id: int
    at: datetime


class PingRequest(_Model):
    pass


# ---------------------------------------------------------------------------
# Sunucu -> İstemci payload'ları
# ---------------------------------------------------------------------------

class UserInfo(_Model):
    id: int
    username: str
    full_name: str
    class_name: str | None = None


class LoginOk(_Model):
    user: UserInfo


class ErrorPayload(_Model):
    code: str
    message: str  # Türkçe, kullanıcıya gösterilebilir


class OptionForStudent(_Model):
    """Şık — is_correct alanı YOK."""

    id: int
    text: str
    order_index: int


class QuestionForStudent(_Model):
    """Öğrenciye gösterilen soru — cevap anahtarı YOK."""

    id: int
    type: Literal["mcq", "classic", "code"]
    text: str
    points: float
    order_index: int
    options: list[OptionForStudent] = Field(default_factory=list)  # sadece mcq
    starter_code: str | None = None                                # sadece code


class ExamForStudent(_Model):
    id: int
    title: str
    questions: list[QuestionForStudent]


class SavedAnswer(_Model):
    selected_option_id: int | None = None
    text_answer: str | None = None
    code: str | None = None


class ExamStart(_Model):
    exam: ExamForStudent
    ends_at: datetime
    server_now: datetime
    saved_answers: dict[int, SavedAnswer] = Field(default_factory=dict)  # anahtar: question_id


class SaveOk(_Model):
    question_id: int
    saved_at: datetime


class SubmitOk(_Model):
    submitted_at: datetime


class ExamEnd(_Model):
    exam_id: int
    reason: Literal["time_up", "instructor_stopped"]


class Pong(_Model):
    server_now: datetime


# Mesaj tipi -> payload modeli
PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    MsgType.LOGIN: LoginRequest,
    MsgType.SAVE_ANSWER: SaveAnswerRequest,
    MsgType.SUBMIT: SubmitRequest,
    MsgType.FOCUS_LOST: FocusLostRequest,
    MsgType.PING: PingRequest,
    MsgType.LOGIN_OK: LoginOk,
    MsgType.ERROR: ErrorPayload,
    MsgType.EXAM_START: ExamStart,
    MsgType.SAVE_OK: SaveOk,
    MsgType.SUBMIT_OK: SubmitOk,
    MsgType.EXAM_END: ExamEnd,
    MsgType.PONG: Pong,
}


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def new_id() -> str:
    """İstek-cevap eşleştirmek için kısa, benzersiz bir id."""
    return uuid.uuid4().hex[:8]


def encode(msg_type: str, payload: BaseModel | None = None, msg_id: str | None = None) -> str:
    """Mesajı gönderilecek JSON metnine çevirir."""
    if msg_type not in PAYLOAD_MODELS:
        raise ValueError(f"Bilinmeyen mesaj tipi: {msg_type}")
    payload_dict = payload.model_dump(mode="json") if payload is not None else {}
    envelope = Envelope(type=msg_type, id=msg_id, payload=payload_dict)
    return envelope.model_dump_json()


def make_error(code: str, message: str, msg_id: str | None = None) -> str:
    """Hazır 'error' mesajı üretir."""
    return encode(MsgType.ERROR, ErrorPayload(code=code, message=message), msg_id)


def decode(raw: str | bytes) -> Envelope:
    """Gelen JSON metnini Envelope'a çevirir. Bozuksa ProtocolError fırlatır."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProtocolError(ErrorCode.BAD_REQUEST, "Mesaj okunamadı (geçersiz JSON).") from None
    try:
        envelope = Envelope.model_validate(data)
    except ValidationError:
        raise ProtocolError(ErrorCode.BAD_REQUEST, "Mesaj biçimi hatalı.") from None
    if envelope.type not in PAYLOAD_MODELS:
        raise ProtocolError(ErrorCode.UNKNOWN_TYPE, f"Bilinmeyen mesaj tipi: {envelope.type}")
    return envelope


def parse_payload(envelope: Envelope) -> BaseModel:
    """Zarfın payload'unu tipine uygun pydantic modeline çevirir."""
    model = PAYLOAD_MODELS[envelope.type]
    try:
        return model.model_validate(envelope.payload)
    except ValidationError:
        raise ProtocolError(ErrorCode.BAD_REQUEST, "Mesajda eksik veya hatalı alan var.") from None
