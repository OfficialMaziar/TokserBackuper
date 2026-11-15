"""Security unit tests: hashing, encryption, path safety, CSRF helpers."""
from __future__ import annotations

import pytest

from app.core.security import (
    csrf_tokens_match,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    mask_secret,
    verify_password,
)
from app.utils import is_safe_archive_member


def test_password_hash_and_verify():
    h = hash_password("CorrectHorse123")
    assert h != "CorrectHorse123"
    assert verify_password("CorrectHorse123", h)
    assert not verify_password("wrong", h)


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("short")


def test_secret_encryption_roundtrip():
    secret = "bot-token-123456:ABCDEF"
    enc = encrypt_secret(secret)
    assert enc != secret
    assert decrypt_secret(enc) == secret


def test_decrypt_with_garbage_returns_empty():
    assert decrypt_secret("not-a-valid-token") == ""


def test_mask_secret():
    assert mask_secret("abcdefghijkl", 3) == "abc******jkl"
    assert mask_secret("") == ""


def test_csrf_comparison():
    assert csrf_tokens_match("abc", "abc")
    assert not csrf_tokens_match("abc", "abd")
    assert not csrf_tokens_match(None, "abc")


@pytest.mark.parametrize("member,expected", [
    ("var/www/index.php", True),
    ("a/b/c.txt", True),
    ("../../etc/passwd", False),
    ("/etc/passwd", False),
    ("a/../../b", False),
    ("..", False),
    ("", False),
    ("C:/Windows/system32", False),
])
def test_safe_archive_member(tmp_path, member, expected):
    assert is_safe_archive_member(member, tmp_path) is expected


def test_totp_verification():
    import base64
    import hashlib
    import hmac
    import struct
    import time

    from app.api.auth import _verify_totp
    from app.core.security import encrypt_secret

    raw = b"12345678901234567890"
    secret_b32 = base64.b32encode(raw).decode().rstrip("=")

    class FakeUser:
        totp_secret = encrypt_secret(secret_b32)

    counter = int(time.time() // 30)
    digest = hmac.new(raw, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    code = f"{(struct.unpack('>I', digest[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"

    assert _verify_totp(FakeUser(), code)
    assert not _verify_totp(FakeUser(), "000000")
