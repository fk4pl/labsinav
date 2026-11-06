"""Kimlik doğrulama: şifre hash'leme ve kullanıcı girişi. (Sahibi: A)"""

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from server.db.models import User
from server.db.session import get_session, write_session
from shared import config

# Kullanıcı bulunamadığında da bcrypt kontrolü yapılır ki cevap süresinden
# "bu kullanıcı adı var mı" anlaşılamasın.
MIN_PASSWORD_LENGTH = 6

_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(rounds=4)).decode()


def hash_password(password: str) -> str:
    """Şifreyi bcrypt ile hash'ler. Veri tabanına bu değer yazılır."""
    salt = bcrypt.gensalt(rounds=config.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Şifre, hash ile eşleşiyor mu?"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:  # bozuk hash veya 72 bayttan uzun şifre
        return False


def authenticate(username: str, password: str) -> User | None:
    """Kullanıcı adı ve şifre doğruysa User döner, değilse None.

    Dönen User'ın school_class alanı da yüklüdür (session kapandıktan sonra okunabilir).
    """
    with get_session() as session:
        user = session.scalar(
            select(User)
            .options(joinedload(User.school_class))
            .where(User.username == username.strip())
        )
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


class PasswordChangeError(Exception):
    """Şifre değiştirilemedi. message: kullanıcıya gösterilebilir Türkçe açıklama."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def change_password(user_id: int, old_password: str, new_password: str) -> None:
    """Eski şifre doğruysa yeni şifreyi kaydeder. Kurala uymazsa PasswordChangeError."""
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise PasswordChangeError(f"Yeni şifre en az {MIN_PASSWORD_LENGTH} karakter olmalı.")
    if new_password == old_password:
        raise PasswordChangeError("Yeni şifre eskisiyle aynı olamaz.")
    # bcrypt yavaştır: kontrol ve hash'leme yazma kilidinin DIŞINDA yapılır.
    with get_session() as session:
        user = session.get(User, user_id)
    if user is None or not verify_password(old_password, user.password_hash):
        raise PasswordChangeError("Mevcut şifre hatalı.")
    new_hash = hash_password(new_password)
    with write_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise PasswordChangeError("Kullanıcı bulunamadı.")
        user.password_hash = new_hash


# ---------------------------------------------------------------------------
# İlk kurulum: veri tabanında hiç eğitmen yoksa ilk eğitmen hesabı oluşturulur
# ---------------------------------------------------------------------------

MAX_USERNAME_LENGTH = 64
MAX_FULL_NAME_LENGTH = 100


class SetupError(Exception):
    """İlk eğitmen hesabı oluşturulamadı. message: kullanıcıya gösterilebilir Türkçe açıklama."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def has_instructor() -> bool:
    """Veri tabanında en az bir eğitmen hesabı var mı?"""
    with get_session() as session:
        return session.scalar(select(User.id).where(User.role == "instructor").limit(1)) is not None


def setup_errors(full_name: str, username: str, password: str, password_again: str) -> list[str]:
    """İlk kurulum formundaki hatalar (boş liste = sorun yok). Veri tabanına bakmaz."""
    errors = []
    if not full_name.strip():
        errors.append("Ad soyad boş olamaz.")
    elif len(full_name.strip()) > MAX_FULL_NAME_LENGTH:
        errors.append(f"Ad soyad en fazla {MAX_FULL_NAME_LENGTH} karakter olabilir.")
    name = username.strip()
    if len(name) < 3 or len(name) > MAX_USERNAME_LENGTH:
        errors.append(f"Kullanıcı adı 3 ile {MAX_USERNAME_LENGTH} karakter arasında olmalı.")
    elif any(ch.isspace() for ch in name):
        errors.append("Kullanıcı adında boşluk olamaz.")
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Şifre en az {MIN_PASSWORD_LENGTH} karakter olmalı.")
    elif password != password_again:
        errors.append("Şifreler birbiriyle aynı değil.")
    return errors


def create_first_instructor(full_name: str, username: str, password: str, password_again: str) -> User:
    """Hiç eğitmen yoksa ilk eğitmen hesabını oluşturur ve döner. Aksi hâlde SetupError."""
    errors = setup_errors(full_name, username, password, password_again)
    if errors:
        raise SetupError("\n".join(errors))
    password_hash = hash_password(password)  # bcrypt yavaştır: kilidin DIŞINDA
    with write_session() as session:
        # Kilidin içinde tekrar bakılır: aynı anda iki kurulum yapılamasın.
        if session.scalar(select(User.id).where(User.role == "instructor").limit(1)) is not None:
            raise SetupError("Zaten bir eğitmen hesabı var; giriş ekranını kullanın.")
        if session.scalar(select(User.id).where(User.username == username.strip())) is not None:
            raise SetupError("Bu kullanıcı adı kullanılıyor.")
        user = User(
            username=username.strip(), full_name=full_name.strip(),
            password_hash=password_hash, role="instructor",
        )
        session.add(user)
        session.flush()
        return user
