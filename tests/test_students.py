"""Sınıf ve öğrenci yönetimi servisleri."""

import pytest

from server.services import students
from server.services.auth import authenticate, change_password
from server.services.students import StudentAdminError
from tests.result_helpers import create_small_exam


def class_id(name: str) -> int:
    return next(c.id for c in students.list_classes() if c.name == name)


def test_create_rename_delete_class(seeded_db) -> None:
    new_id = students.create_class("  2. Öğretim   A ")
    assert class_id("2. Öğretim A") == new_id
    students.rename_class(new_id, "2. Öğretim B")
    assert class_id("2. Öğretim B") == new_id
    students.delete_class(new_id)
    assert all(c.id != new_id for c in students.list_classes())


def test_class_name_rules(seeded_db) -> None:
    with pytest.raises(StudentAdminError, match="boş"):
        students.create_class("   ")
    with pytest.raises(StudentAdminError, match="zaten var"):
        students.create_class("1. öğretim a")  # büyük-küçük harf farkı sayılmaz


def test_class_with_students_cannot_be_deleted(seeded_db) -> None:
    with pytest.raises(StudentAdminError, match="15 öğrenci var"):
        students.delete_class(class_id("1. Öğretim A"))


def test_class_with_exam_cannot_be_deleted(seeded_db) -> None:
    create_small_exam()  # 1. Öğretim A'ya ait sınav
    cid = class_id("1. Öğretim A")
    students.move_students([s.id for s in students.list_students(cid)], class_id("1. Öğretim B"))
    with pytest.raises(StudentAdminError, match="sınav var"):
        students.delete_class(cid)


def test_create_student_with_initial_password(seeded_db) -> None:
    cid = class_id("1. Öğretim A")
    students.create_student("260101099", "  Yeni   Öğrenci ", cid)
    row = next(s for s in students.list_students(cid) if s.student_no == "260101099")
    assert row.full_name == "Yeni Öğrenci"
    assert authenticate("260101099", "260101099") is not None


def test_create_student_rejects_duplicate_and_invalid(seeded_db) -> None:
    cid = class_id("1. Öğretim A")
    with pytest.raises(StudentAdminError, match="zaten var"):
        students.create_student("260101001", "Tekrar", cid)
    with pytest.raises(StudentAdminError, match="rakam"):
        students.create_student("26A", "Harfli", cid)
    with pytest.raises(StudentAdminError, match="Ad soyad boş"):
        students.create_student("260101098", "  ", cid)


def test_update_student(seeded_db) -> None:
    cid = class_id("1. Öğretim A")
    student = students.list_students(cid)[0]
    students.update_student(student.id, "260109999", "Değişen Ad")
    updated = next(s for s in students.list_students(cid) if s.id == student.id)
    assert (updated.student_no, updated.full_name) == ("260109999", "Değişen Ad")
    with pytest.raises(StudentAdminError, match="zaten var"):
        students.update_student(student.id, "260101002", "Değişen Ad")


def test_reset_password(seeded_db) -> None:
    student = students.list_students(class_id("1. Öğretim A"))[0]
    change_password(student.id, student.student_no, "yenisifre123")
    assert authenticate(student.student_no, student.student_no) is None
    students.reset_password(student.id)
    assert authenticate(student.student_no, student.student_no) is not None  # şifre = öğrenci no


def test_move_students(seeded_db) -> None:
    a, b = class_id("1. Öğretim A"), class_id("1. Öğretim B")
    ids = [s.id for s in students.list_students(a)[:2]]
    students.move_students(ids, b)
    assert len(students.list_students(a)) == 13
    assert len(students.list_students(b)) == 17


def test_existing_usernames(seeded_db) -> None:
    found = students.existing_usernames(["260101001", "egitmen", "999"])
    assert found == {"260101001": "1. Öğretim A", "egitmen": "eğitmen hesabı"}
