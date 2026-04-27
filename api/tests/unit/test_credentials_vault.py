# ABOUTME: Unit tests for credentials_vault — round-trip + rotation + missing-key paths.
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from config import settings
from services import credentials_vault


@pytest.fixture(autouse=True)
def _restore_key():
    original = settings.credentials_encryption_key
    yield
    settings.credentials_encryption_key = original


def test_round_trip_with_default_key() -> None:
    cipher = credentials_vault.encrypt("super-secret-token")
    plain = credentials_vault.decrypt(cipher)
    assert plain == "super-secret-token"


def test_empty_plaintext_rejected() -> None:
    with pytest.raises(ValueError):
        credentials_vault.encrypt("")


def test_rotation_decrypts_with_legacy_key() -> None:
    """Encrypt with key A, then prepend key B; key A still decrypts.

    Mirrors the rotation playbook: prepend new key, leave the old key
    in the list until every credential has been re-saved through the
    admin UI."""
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    settings.credentials_encryption_key = key_a
    cipher = credentials_vault.encrypt("legacy-token")

    # Now rotate: B is primary, A still trusted for decrypt.
    settings.credentials_encryption_key = f"{key_b},{key_a}"
    assert credentials_vault.decrypt(cipher) == "legacy-token"

    # New writes encrypt under B; the legacy A-encrypted cipher is unchanged.
    cipher_b = credentials_vault.encrypt("new-token")
    assert cipher_b != cipher
    assert credentials_vault.decrypt(cipher_b) == "new-token"


def test_decrypt_after_key_removal_raises() -> None:
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    settings.credentials_encryption_key = key_a
    cipher = credentials_vault.encrypt("orphaned")

    # Remove A entirely; B can't decrypt.
    settings.credentials_encryption_key = key_b
    with pytest.raises(credentials_vault.VaultDecryptError):
        credentials_vault.decrypt(cipher)


def test_new_key_is_valid_fernet() -> None:
    key = credentials_vault.new_key()
    Fernet(key.encode())  # raises if malformed
