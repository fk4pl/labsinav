import pytest

from server.services.auth import (
    PasswordChangeError,
    authenticate,
    change_password,
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
