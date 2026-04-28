# ABOUTME: Unit tests for auth_service TOTP MultiFernet rotation (Phase 5 Sprint 0).
# ABOUTME: Mirrors test_credentials_vault — encrypt with primary, decrypt with any.
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from config import settings
from services import auth_service


@pytest.fixture(autouse=True)
def _restore_keys():
    """Snapshot + restore the two TOTP key settings so tests don't leak."""
    original_keys = settings.totp_encryption_keys
    original_single = settings.totp_encryption_key
    yield
    settings.totp_encryption_keys = original_keys
    settings.totp_encryption_key = original_single


def test_round_trip_with_single_key() -> None:
    """Default (single-key) configuration: encrypt + decrypt are inverse."""
    enc = auth_service._encrypt_totp_secret("JBSWY3DPEHPK3PXP")
    plain = auth_service._decrypt_totp_secret(enc)
    assert plain == "JBSWY3DPEHPK3PXP"


def test_rotation_decrypts_with_legacy_key() -> None:
    """Encrypt under key A, rotate to (B, A), legacy ciphertext still decrypts.

    The whole point of MultiFernet on the TOTP path: rotating the primary
    key doesn't strand existing rows."""
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    settings.totp_encryption_keys = key_a
    enc_a = auth_service._encrypt_totp_secret("legacy-secret")

    settings.totp_encryption_keys = f"{key_b},{key_a}"
    assert auth_service._decrypt_totp_secret(enc_a) == "legacy-secret"

    # Newly issued tokens encrypt under the new primary B.
    enc_b = auth_service._encrypt_totp_secret("new-secret")
    assert enc_b != enc_a
    assert auth_service._decrypt_totp_secret(enc_b) == "new-secret"


def test_decrypt_after_key_removal_raises() -> None:
    """Drop the original key without re-encrypting → decrypt fails loudly.

    Operationally the recovery is: re-add the missing key to the
    rotation list, OR have the user disable + re-enable 2FA so the row
    is re-encrypted under the current primary."""
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    settings.totp_encryption_keys = key_a
    enc = auth_service._encrypt_totp_secret("orphaned-secret")

    settings.totp_encryption_keys = key_b
    with pytest.raises(InvalidToken):
        auth_service._decrypt_totp_secret(enc)


def test_legacy_single_key_field_falls_back() -> None:
    """`totp_encryption_keys` empty → fall back to `totp_encryption_key`.

    Existing dev / test environments only set TOTP_ENCRYPTION_KEY; they
    must keep working without setting the new variable."""
    legacy_key = Fernet.generate_key().decode()
    settings.totp_encryption_keys = ""
    settings.totp_encryption_key = legacy_key

    enc = auth_service._encrypt_totp_secret("dev-secret")
    assert auth_service._decrypt_totp_secret(enc) == "dev-secret"


def test_both_unset_raises_at_resolve() -> None:
    """Both fields empty → startup-class error, not silent skip."""
    settings.totp_encryption_keys = ""
    settings.totp_encryption_key = ""
    with pytest.raises(RuntimeError, match="totp_encryption_keys"):
        auth_service._resolve_totp_keys()


def test_keys_field_wins_over_single_when_both_set() -> None:
    """`totp_encryption_keys` is the canonical source when set; the
    legacy `totp_encryption_key` is ignored."""
    primary = Fernet.generate_key().decode()
    other = Fernet.generate_key().decode()

    settings.totp_encryption_keys = primary
    settings.totp_encryption_key = other  # should not be consulted

    keys = auth_service._resolve_totp_keys()
    assert keys == [primary]
