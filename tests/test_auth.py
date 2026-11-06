import pytest

from server.db.models import User
from server.db.session import write_session
from server.services.auth import (
    PasswordChangeError,
    SetupError,
    authenticate,
    change_password,
    create_first_instructor,
    has_instructor,
    hash_password,
    verify_password,
)


def test_hash_and_verify() -> None:
    hashed = hash_password("gizli123")
    assert hashed != "gizli123"
    assert verify_password("gizli123", hashed)
    assert not verify_password("yanlis", hashed)


def test_verify_with_broken_hash_returns_false() -> None:
    assert not verify_password("x", "bozuk-hash")


def test_authenticate_student(seeded_db) -> None:
    user = authenticate("260101001", "260101001")
    assert user is not None
    assert user.role == "student"
    assert user.full_name == "Ahmet Yılmaz"
    assert user.school_class is not None and user.school_class.name == "1. Öğretim A"


def test_authenticate_instructor(seeded_db) -> None:
    user = authenticate("egitmen", "egitmen123")
    assert user is not None and user.role == "instructor"


def test_authenticate_wrong_password(seeded_db) -> None:
    assert authenticate("260101001", "yanlis") is None


def test_authenticate_unknown_user(seeded_db) -> None:
    assert authenticate("999999999", "999999999") is None


def test_authenticate_strips_username_spaces(seeded_db) -> None:
    assert authenticate("  260101002 ", "260101002") is not None


def test_change_password(seeded_db) -> None:
    user = authenticate("egitmen", "egitmen123")
    assert user is not None
    change_password(user.id, "egitmen123", "yenisifre1")
    assert authenticate("egitmen", "egitmen123") is None
    assert authenticate("egitmen", "yenisifre1") is not None


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("yanlis", "yenisifre1", "Mevcut şifre hatalı"),
        ("egitmen123", "kisa", "en az 6"),
        ("egitmen123", "egitmen123", "aynı olamaz"),
    ],
)
def test_change_password_rejected(seeded_db, old: str, new: str, expected: str) -> None:
    user = authenticate("egitmen", "egitmen123")
    assert user is not None
    with pytest.raises(PasswordChangeError, match=expected):
        change_password(user.id, old, new)
    assert authenticate("egitmen", "egitmen123") is not None


# ---------------------------------------------------------------------------
# İlk kurulum
# ---------------------------------------------------------------------------

def test_has_instructor(seeded_db) -> None:
    assert has_instructor()


def test_empty_db_has_no_instructor(empty_db) -> None:
    assert not has_instructor()


def test_create_first_instructor_then_login(empty_db) -> None:
    user = create_first_instructor("  Ayşe Korkmaz ", " ayse ", "gizli123", "gizli123")
    assert (user.username, user.full_name, user.role) == ("ayse", "Ayşe Korkmaz", "instructor")
    assert has_instructor()
    assert authenticate("ayse", "gizli123") is not None


@pytest.mark.parametrize("args, message", [
    (("", "ayse", "gizli123", "gizli123"), "Ad soyad boş olamaz."),
    (("Ayşe", "ay", "gizli123", "gizli123"), "Kullanıcı adı 3 ile 64"),
    (("Ayşe", "ay se", "gizli123", "gizli123"), "boşluk olamaz"),
    (("Ayşe", "ayse", "123", "123"), "en az 6 karakter"),
    (("Ayşe", "ayse", "gizli123", "gizli124"), "Şifreler birbiriyle aynı değil."),
])
def test_create_first_instructor_validation(empty_db, args: tuple, message: str) -> None:
    with pytest.raises(SetupError, match=message):
        create_first_instructor(*args)
    assert not has_instructor()


def test_second_first_instructor_is_rejected(empty_db) -> None:
    create_first_instructor("Ayşe", "ayse", "gizli123", "gizli123")
    with pytest.raises(SetupError, match="Zaten bir eğitmen"):
        create_first_instructor("Mehmet", "mehmet", "gizli123", "gizli123")


def test_first_instructor_username_taken_by_student(empty_db) -> None:
    """Eğitmen yok ama kullanıcı adı bir öğrencide kullanılıyor."""
    with write_session() as session:
        session.add(User(username="260101001", full_name="Öğrenci", password_hash="x", role="student"))
    with pytest.raises(SetupError, match="kullanılıyor"):
        create_first_instructor("Ayşe", "260101001", "gizli123", "gizli123")
