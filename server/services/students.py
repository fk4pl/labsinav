"""Sınıf ve öğrenci yönetimi: ekle, düzenle, sil, şifre sıfırla, sınıfa taşı. (Sahibi: D — P6)

Arayüz (instructor_app/ui/students.py) veri tabanına doğrudan dokunmaz; bu fonksiyonları çağırır.
Hatalar StudentAdminError ile, kullanıcıya gösterilebilir Türkçe mesajla bildirilir.

Kurallar:
- Öğrenci kullanıcı adı = öğrenci no (sadece rakam). Başlangıç şifresi = öğrenci no.
- Öğrencisi olan sınıf silinemez (önce öğrenciler taşınmalı). Sınavı olan sınıf da silinemez
  (geçmiş sonuçlar bozulmasın).
- bcrypt hash'i yavaştır (~0,25 sn); yazma kilidini meşgul etmemek için kilidin DIŞINDA hesaplanır.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.db.models import Exam, SchoolClass, User
from server.db.session import get_session, write_session
from server.services import exam_admin
from server.services.auth import hash_password
from server.services.exam_admin import ClassRow
from server.services.question_bank import turkish_lower

MAX_CLASS_NAME = 100
MAX_STUDENT_NO = 20
MAX_FULL_NAME = 150


class StudentAdminError(Exception):
    """Kural ihlali. message: kullanıcıya gösterilebilir Türkçe açıklama."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class StudentRow:
    id: int
    student_no: str
    full_name: str
    class_id: int | None


# ---------------------------------------------------------------------------
# Doğrulama (içe aktarma da kullanır)
# ---------------------------------------------------------------------------

def check_student_no(value: str) -> str | None:
    """Öğrenci no geçerliyse None, değilse Türkçe hata nedeni döner."""
    if not value:
        return "Öğrenci no boş."
    if not value.isdigit() or not value.isascii():
        return f"Öğrenci no sadece rakamlardan oluşmalı: '{value}'."
    if len(value) > MAX_STUDENT_NO:
        return f"Öğrenci no en fazla {MAX_STUDENT_NO} haneli olabilir."
    return None


def check_full_name(value: str) -> str | None:
    if not value:
        return "Ad soyad boş."
    if len(value) > MAX_FULL_NAME:
        return f"Ad soyad en fazla {MAX_FULL_NAME} karakter olabilir."
    return None


def clean_text(value: str) -> str:
    """Baştaki/sondaki ve aradaki fazla boşlukları temizler."""
    return " ".join(value.split())


def _valid_student(student_no: str, full_name: str) -> tuple[str, str]:
    student_no, full_name = clean_text(student_no), clean_text(full_name)
    error = check_student_no(student_no) or check_full_name(full_name)
    if error:
        raise StudentAdminError(error)
    return student_no, full_name


# ---------------------------------------------------------------------------
# Sınıflar
# ---------------------------------------------------------------------------

def list_classes() -> list[ClassRow]:
    """Tüm sınıflar ve öğrenci sayıları (Sınavlar sekmesiyle aynı liste)."""
    return exam_admin.list_classes()


def create_class(name: str) -> int:
    with write_session() as session:
        school_class = SchoolClass(name=_check_class_name(session, name))
        session.add(school_class)
        session.flush()
        return school_class.id


def rename_class(class_id: int, name: str) -> None:
    with write_session() as session:
        school_class = get_class(session, class_id)
        school_class.name = _check_class_name(session, name, exclude_id=class_id)


def delete_class(class_id: int) -> None:
    """Boş ve sınavı olmayan sınıfı siler."""
    with write_session() as session:
        school_class = get_class(session, class_id)
        students = session.scalar(select(func.count(User.id)).where(User.class_id == class_id))
        if students:
            raise StudentAdminError(
                f"'{school_class.name}' sınıfında {students} öğrenci var; önce öğrencileri başka sınıfa taşıyın."
            )
        exams = session.scalar(select(func.count(Exam.id)).where(Exam.class_id == class_id))
        if exams:
            raise StudentAdminError(
                f"'{school_class.name}' sınıfına ait {exams} sınav var; geçmiş sonuçlar bozulmasın diye silinemez."
            )
        session.delete(school_class)


def get_class(session: Session, class_id: int) -> SchoolClass:
    school_class = session.get(SchoolClass, class_id)
    if school_class is None:
        raise StudentAdminError("Sınıf bulunamadı (silinmiş olabilir).")
    return school_class


def _check_class_name(session: Session, name: str, exclude_id: int | None = None) -> str:
    name = clean_text(name)
    if not name:
        raise StudentAdminError("Sınıf adı boş olamaz.")
    if len(name) > MAX_CLASS_NAME:
        raise StudentAdminError(f"Sınıf adı en fazla {MAX_CLASS_NAME} karakter olabilir.")
    for other_id, other_name in session.execute(select(SchoolClass.id, SchoolClass.name)):
        if other_id != exclude_id and turkish_lower(other_name) == turkish_lower(name):
            raise StudentAdminError(f"'{other_name}' adında bir sınıf zaten var.")
    return name


# ---------------------------------------------------------------------------
# Öğrenciler
# ---------------------------------------------------------------------------

def list_students(class_id: int) -> list[StudentRow]:
    """Sınıftaki öğrenciler, öğrenci no'ya göre sıralı."""
    query = (
        select(User)
        .where(User.role == "student", User.class_id == class_id)
        .order_by(User.username)
    )
    with get_session() as session:
        return [_to_row(user) for user in session.scalars(query)]


def existing_usernames(usernames: list[str]) -> dict[str, str]:
    """Verilen kullanıcı adlarından veri tabanında olanlar → bulundukları sınıfın adı (yoksa rol açıklaması)."""
    if not usernames:
        return {}
    query = select(User).where(User.username.in_(usernames))
    with get_session() as session:
        return {user.username: _place_of(user) for user in session.scalars(query)}


def create_student(student_no: str, full_name: str, class_id: int) -> int:
    """Yeni öğrenci ekler. Başlangıç şifresi = öğrenci no."""
    student_no, full_name = _valid_student(student_no, full_name)
    password_hash = hash_password(student_no)  # kilidin dışında (yavaş)
    with write_session() as session:
        get_class(session, class_id)
        _check_username_free(session, student_no)
        user = User(username=student_no, full_name=full_name, password_hash=password_hash,
                    role="student", class_id=class_id)
        session.add(user)
        session.flush()
        return user.id


def update_student(student_id: int, student_no: str, full_name: str) -> None:
    """Öğrenci no ve ad soyadı değiştirir. Şifre değişmez."""
    student_no, full_name = _valid_student(student_no, full_name)
    with write_session() as session:
        user = _get_student(session, student_id)
        if student_no != user.username:
            _check_username_free(session, student_no)
        user.username, user.full_name = student_no, full_name


def reset_password(student_id: int) -> None:
    """Şifreyi öğrenci no'ya döndürür."""
    with get_session() as session:
        username = _get_student(session, student_id).username
    password_hash = hash_password(username)  # kilidin dışında (yavaş)
    with write_session() as session:
        _get_student(session, student_id).password_hash = password_hash


def move_students(student_ids: list[int], class_id: int) -> None:
    with write_session() as session:
        get_class(session, class_id)
        for student_id in student_ids:
            _get_student(session, student_id).class_id = class_id


def _get_student(session: Session, student_id: int) -> User:
    user = session.get(User, student_id)
    if user is None or user.role != "student":
        raise StudentAdminError("Öğrenci bulunamadı (silinmiş olabilir).")
    return user


def _check_username_free(session: Session, username: str) -> None:
    other = session.scalar(select(User).where(User.username == username))
    if other is not None:
        raise StudentAdminError(f"{username} numaralı kullanıcı zaten var ({_place_of(other)}).")


def _place_of(user: User) -> str:
    if user.role != "student":
        return "eğitmen hesabı"
    return user.school_class.name if user.school_class else "sınıfsız"


def _to_row(user: User) -> StudentRow:
    return StudentRow(id=user.id, student_no=user.username, full_name=user.full_name, class_id=user.class_id)
