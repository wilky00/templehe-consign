# ABOUTME: Phase 4 Sprint 7 — Fernet-encrypted vault for integration credentials.
# ABOUTME: Plaintext only ever exists in memory; DB stores encrypted bytes.
"""Credentials vault — Phase 4 Sprint 7.

Why a separate vault module instead of "just call Fernet inline":

- Single source of key derivation. ``totp_encryption_key`` is keyed
  off the same env-var pattern, but TOTP secrets and integration
  credentials live on different rotation cadences. The vault picks
  ``credentials_encryption_key`` first; falls back to
  ``totp_encryption_key`` so dev / test don't need two secrets set.
- MultiFernet rotation. Both env vars accept a comma-separated list of
  keys; the *first* key is the primary (used for new writes), all keys
  are tried on decrypt. Rotate by prepending a new key, redeploying,
  then re-saving each credential through the admin UI to flip onto the
  new primary. Old keys can be removed once every credential has been
  re-saved. (Not automatic — admin's call.)
- Hosting migration. Phase 4 ships DB-backed Fernet because Fly secrets
  is the only secret store available pre-GCP. ADR-020 commits to a
  clean swap: GCP migration replaces ``set/get`` with Secret Manager
  reads — the call sites don't change.

The vault's public surface is intentionally small: ``encrypt``,
``decrypt``, ``new_key``. Persistence (SELECT / INSERT / UPDATE) lives
in ``admin_credentials_service``; this module is pure crypto.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from config import settings


class VaultDecryptError(RuntimeError):
    """Raised when decrypt fails against every configured Fernet key.

    Distinct from a missing-row case; the row exists, but no key in the
    rotation list can recover it. Operationally that means a key was
    removed before its credentials were re-saved — recovery is a re-save
    by an admin who knows the original plaintext."""


def _resolve_keys() -> list[str]:
    """Pick the active key material.

    Comma-separated list, first key is the encrypt-primary. Falls back
    to the TOTP key when the dedicated credentials key isn't set so
    dev / test environments don't need two Fernet secrets configured.
    """
    raw = settings.credentials_encryption_key.strip() or settings.totp_encryption_key.strip()
    if not raw:
        raise RuntimeError(
            "credentials_encryption_key (or totp_encryption_key) must be set; "
            "neither is configured."
        )
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("credentials_encryption_key parsed to empty list.")
    return keys


def _build() -> MultiFernet:
    keys = _resolve_keys()
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(plaintext: str) -> bytes:
    """Encrypt ``plaintext`` with the primary key.

    Raises ``RuntimeError`` if no key material is configured.
    Raises ``ValueError`` if ``plaintext`` is empty — empty credentials
    are almost always a UI bug, not an intentional save.
    """
    if not plaintext:
        raise ValueError("plaintext must not be empty")
    return _build().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    """Decrypt ``ciphertext`` against any configured key.

    Raises :class:`VaultDecryptError` if no key in the rotation list
    can recover the plaintext. Re-raised so callers can surface "key
    rotation broke this credential — re-save via the admin UI" rather
    than a generic 500."""
    try:
        return _build().decrypt(ciphertext).decode()
    except InvalidToken as exc:
        raise VaultDecryptError(
            "Could not decrypt credential — key rotation may have removed the original key."
        ) from exc


def new_key() -> str:
    """Generate a fresh Fernet key.

    Used in tests + ops scripts. Not used by the runtime path."""
    return Fernet.generate_key().decode()
