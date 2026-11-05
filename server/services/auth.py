"""Kimlik doğrulama: şifre hash'leme ve kullanıcı girişi. (Sahibi: A)"""

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from server.db.models import User
from server.db.session import get_session
from shared import config

# Kullanıcı bulunamadığında da bcrypt kontrolü yapılır ki cevap süresinden
# "bu kullanıcı adı var mı" anlaşılamasın.
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
