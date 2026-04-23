# ABOUTME: Unit tests for auth_service pure functions — no DB, no network.
# ABOUTME: DB-dependent paths are covered by integration tests in test_auth_flows.py.
from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
import pytest

from config import settings
from services.auth_service import (
    _TYPE_ACCESS,
    _TYPE_PARTIAL,
    _TYPE_RESET_PASSWORD,
    _TYPE_VERIFY_EMAIL,
    _create_signed_token,
    _decode_token,
    _decrypt_totp_secret,
    _device_fingerprint,
    _encrypt_totp_secret,
    _hash_recovery_code,
    create_access_token,
    create_partial_token,
    hash_password,
    verify_password,
)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_hash_password_returns_bcrypt_hash():
    hashed = hash_password("TestPassword1!")
    assert hashed.startswith("$2b$")


def test_verify_password_correct():
    hashed = hash_password("TestPassword1!")
    assert verify_password("TestPassword1!", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("TestPassword1!")
    assert verify_password("WrongPassword1!", hashed) is False


def test_hash_password_is_salted():
    h1 = hash_password("TestPassword1!")
    h2 = hash_password("TestPassword1!")
    assert h1 != h2  # bcrypt salt is random


# ---------------------------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------------------------


def test_create_access_token_decodes_correctly():
    user_id = uuid.uuid4()
    token = create_access_token(user_id, "test@example.com", "customer")
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == str(user_id)
    assert payload["email"] == "test@example.com"
    assert payload["role"] == "customer"
    assert payload["type"] == _TYPE_ACCESS


def test_create_partial_token_has_correct_type():
    user_id = uuid.uuid4()
    token = create_partial_token(user_id)
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["type"] == _TYPE_PARTIAL
    assert payload["sub"] == str(user_id)


def test_decode_token_rejects_wrong_type():
    user_id = uuid.uuid4()
    token = create_partial_token(user_id)

    with pytest.raises(jwt.PyJWTError):
        _decode_token(token, _TYPE_ACCESS)


def test_decode_token_rejects_expired():
    expired_token = _create_signed_token(
        {"sub": str(uuid.uuid4()), "type": _TYPE_VERIFY_EMAIL},
        timedelta(seconds=-1),
    )
    with pytest.raises(jwt.PyJWTError):
        _decode_token(expired_token, _TYPE_VERIFY_EMAIL)


def test_decode_token_accepts_valid():
    user_id = uuid.uuid4()
    token = _create_signed_token(
        {"sub": str(user_id), "type": _TYPE_RESET_PASSWORD},
        timedelta(minutes=30),
    )
    payload = _decode_token(token, _TYPE_RESET_PASSWORD)
    assert payload["sub"] == str(user_id)


def test_decode_token_rejects_alg_none():
    # PyJWT must refuse unsigned tokens even if the header claims alg=none.
    # Forged via jwt.encode with algorithm="none" and empty key.
    unsigned = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": _TYPE_ACCESS},
        key="",
        algorithm="none",
    )
    with pytest.raises(jwt.PyJWTError):
        _decode_token(unsigned, _TYPE_ACCESS)


# ---------------------------------------------------------------------------
# TOTP encryption
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_totp_secret_roundtrip():
    secret = "JBSWY3DPEHPK3PXP"
    encrypted = _encrypt_totp_secret(secret)
    assert encrypted != secret
    assert _decrypt_totp_secret(encrypted) == secret


def test_encrypt_totp_is_non_deterministic():
    secret = "JBSWY3DPEHPK3PXP"
    enc1 = _encrypt_totp_secret(secret)
    enc2 = _encrypt_totp_secret(secret)
    assert enc1 != enc2  # Fernet uses a random IV


# ---------------------------------------------------------------------------
# Recovery code hashing
# ---------------------------------------------------------------------------


def test_hash_recovery_code_is_deterministic():
    code = "ABCDEF1234567890"
    assert _hash_recovery_code(code) == _hash_recovery_code(code)


def test_hash_recovery_code_differs_for_different_codes():
    assert _hash_recovery_code("AAAA") != _hash_recovery_code("BBBB")


# ---------------------------------------------------------------------------
# Device fingerprinting
# ---------------------------------------------------------------------------


def test_device_fingerprint_is_deterministic():
    fp1 = _device_fingerprint("Mozilla/5.0", "192.168.1.10")
    fp2 = _device_fingerprint("Mozilla/5.0", "192.168.1.20")  # same /24 prefix
    assert fp1 == fp2  # same UA + same /24 → same fingerprint


def test_device_fingerprint_differs_for_different_ua():
    fp1 = _device_fingerprint("Mozilla/5.0", "192.168.1.10")
    fp2 = _device_fingerprint("curl/7.0", "192.168.1.10")
    assert fp1 != fp2


def test_device_fingerprint_handles_none():
    fp = _device_fingerprint(None, None)
    assert isinstance(fp, str)
    assert len(fp) == 64  # SHA-256 hex digest


# ---------------------------------------------------------------------------
# Password schema validation
# ---------------------------------------------------------------------------


def test_password_schema_rejects_short():
    from pydantic import ValidationError

    from schemas.auth import RegisterRequest

    with pytest.raises(ValidationError, match="12 characters"):
        RegisterRequest(email="a@b.com", password="Short1!", first_name="A", last_name="B")


def test_password_schema_rejects_no_uppercase():
    from pydantic import ValidationError

    from schemas.auth import RegisterRequest

    with pytest.raises(ValidationError, match="uppercase"):
        RegisterRequest(email="a@b.com", password="alllowercase1!", first_name="A", last_name="B")


def test_password_schema_rejects_no_special():
    from pydantic import ValidationError

    from schemas.auth import RegisterRequest

    with pytest.raises(ValidationError, match="special"):
        RegisterRequest(email="a@b.com", password="NoSpecialChar1", first_name="A", last_name="B")


def test_password_schema_accepts_valid():
    from schemas.auth import RegisterRequest

    req = RegisterRequest(
        email="user@example.com",
        password="ValidPass1!xx",
        first_name="Jane",
        last_name="Doe",
        tos_version="1",
        privacy_version="1",
    )
    assert req.email == "user@example.com"


def test_register_request_strips_name_whitespace():
    from schemas.auth import RegisterRequest

    req = RegisterRequest(
        email="user@example.com",
        password="ValidPass1!xx",
        first_name="  Jane  ",
        last_name="  Doe  ",
        tos_version="1",
        privacy_version="1",
    )
    assert req.first_name == "Jane"
    assert req.last_name == "Doe"
