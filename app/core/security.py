"""Security primitives: password hashing, secret encryption, CSRF, tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# ---------------------------------------------------------------------------
# Password hashing (Argon2id via argon2-cffi, bcrypt fallback)
# ---------------------------------------------------------------------------
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    _ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
    _HAS_ARGON = True
except Exception:  # pragma: no cover
    _HAS_ARGON = False
    _ph = None  # type: ignore

import bcrypt as _bcrypt


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if _HAS_ARGON:
        return _ph.hash(password)
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not password or not hashed:
        return False
    if hashed.startswith("$argon2"):
        if not _HAS_ARGON:
            return False
        try:
            return _ph.verify(hashed, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        except Exception:
            return False
    if hashed.startswith("$2"):
        try:
            return _bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False
    return False


def password_needs_rehash(hashed: str) -> bool:
    if _HAS_ARGON and hashed.startswith("$argon2"):
        try:
            return _ph.check_needs_rehash(hashed)
        except Exception:
            return False
    return False


# ---------------------------------------------------------------------------
# Symmetric encryption for stored secrets (tokens, DB passwords, keys)
# ---------------------------------------------------------------------------
def _fernet() -> Fernet:
    raw = settings.encryption_key.encode("utf-8")
    # Derive a stable 32-byte urlsafe key from the configured secret.
    digest = hashlib.sha256(raw).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    if plaintext is None:
        plaintext = ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return ""


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}{'*' * (len(value) - visible * 2)}{value[-visible:]}"


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
