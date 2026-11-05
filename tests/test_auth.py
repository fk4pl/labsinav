from server.services.auth import authenticate, hash_password, verify_password


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
