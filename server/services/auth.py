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
