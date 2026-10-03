"""Encryption-at-rest for provider API keys + UI masking.

Design
------
* Values are encrypted with **Fernet (AES-128-CBC + HMAC)** before they are
  written to ``ProviderCredential.encValue``.
* Ciphertexts are stored as ``v1.<key_id>.<fernet-token>`` so the payload
  itself records WHICH key encrypted it — this is what makes **key rotation**
  possible: new values are written with the current primary key while old
  values keep decrypting with their recorded key until rotated.
* Keys are resolved from the environment, in priority order:

  1. ``ADMIN_CONFIG_ENC_KEYS`` — JSON object mapping key-ids to base64url
     Fernet keys, e.g. ``{"k2": "...", "k1": "..."}``. The LAST entry is the
     primary (encryption) key; the others decrypt only.
  2. ``ADMIN_CONFIG_ENC_KEY`` — single base64url Fernet key (id ``"v1"``).
  3. ``JWT_SECRET`` — the raw signing secret is used to derive a Fernet key
     (dev/self-host fallback only; a loud warning is logged).

  Generate a key with::

      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

* Decryption happens ONLY server-side (API responses always carry
  ``masked_value``; the plaintext never leaves the backend).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger("voice-agent-saas-crypto")

_PREFIX = "v1"
_env_cache: Optional[Dict[str, "object"]] = None


class EncryptionUnavailable(RuntimeError):
    """Raised when no usable encryption key is configured."""


def _load_fernet_cls():
    try:
        from cryptography.fernet import Fernet  # type: ignore
    except ImportError as e:  # pragma: no cover - dependency guard
        raise EncryptionUnavailable(
            "cryptography package is required for provider key encryption: "
            "pip install cryptography"
        ) from e
    return Fernet


def _derive_key_from_secret(secret: str) -> bytes:
    """Derive a valid Fernet key from an arbitrary secret (dev fallback)."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _keyring() -> Dict[str, object]:
    """{key_id: Fernet} in env-declaration order; last entry is primary."""
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    Fernet = _load_fernet_cls()
    ring: Dict[str, object] = {}
    # Legacy single key joins the ring FIRST (id "v1") so that when
    # ADMIN_CONFIG_ENC_KEYS is present the LAST entry of that map is ALWAYS the
    # primary (encryption) key — deterministic rotation semantics.
    single = os.getenv("ADMIN_CONFIG_ENC_KEY", "").strip()
    if single:
        ring["v1"] = Fernet(single.encode("utf-8"))
    raw_keys = os.getenv("ADMIN_CONFIG_ENC_KEYS", "").strip()
    if raw_keys:
        try:
            parsed = json.loads(raw_keys)
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("must be a non-empty JSON object")
            for kid, key in parsed.items():
                if str(kid) != "v1":  # never shadow the legacy single-key id silently
                    ring[str(kid)] = Fernet(str(key).encode("utf-8"))
        except Exception as e:
            raise EncryptionUnavailable(
                f"ADMIN_CONFIG_ENC_KEYS is invalid ({e}); expected a JSON "
                "object mapping key ids to Fernet keys."
            ) from e
    if not ring:
        # Dev/self-host fallback: derive from JWT secret so the feature works
        # out of the box. At-rest confidentiality then equals the JWT secret's
        # — acceptable for a demo, NOT for production.
        from ..config import JWT_SECRET

        if JWT_SECRET in ("", "dev-secret-change-me"):
            logger.warning(
                "🔓 No ADMIN_CONFIG_ENC_KEY(S) configured AND JWT_SECRET is the "
                "default — provider credentials are encrypted with a publicly-"
                "known key. Set ADMIN_CONFIG_ENC_KEY before storing real keys."
            )
        else:
            logger.warning(
                "🔓 ADMIN_CONFIG_ENC_KEY(S) not set — deriving the encryption "
                "key from JWT_SECRET (dev fallback). Set ADMIN_CONFIG_ENC_KEY "
                "for production."
            )
        ring["v1"] = Fernet(_derive_key_from_secret(JWT_SECRET or "dev-secret"))
    _env_cache = ring
    return ring


def _primary_key_id() -> str:
    ring = _keyring()
    return next(reversed(ring))


def reset_cache_for_tests() -> None:
    global _env_cache
    _env_cache = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def encrypt_secret(value: str) -> Tuple[str, str]:
    """Encrypt a raw secret. Returns ``(ciphertext, masked_display)``."""
    if not value:
        raise ValueError("secret must be a non-empty string")
    from .credential_service import mask_secret  # local import avoids cycle

    kid = _primary_key_id()
    token = _keyring()[kid].encrypt(value.encode("utf-8")).decode("utf-8")
    ciphertext = f"{_PREFIX}.{kid}.{token}"
    return ciphertext, mask_secret(value)


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored ciphertext. Server-side only — never call from a route
    that returns the result to a client."""
    if not ciphertext:
        raise ValueError("ciphertext empty")
    raw = ciphertext
    kid = _primary_key_id()
    if raw.startswith(f"{_PREFIX}."):
        parts = raw.split(".", 2)
        if len(parts) != 3:
            raise ValueError("malformed ciphertext")
        _, kid, raw = parts
    ring = _keyring()
    f = ring.get(kid)
    if f is None:
        raise EncryptionUnavailable(
            f"ciphertext was encrypted with key id '{kid}', which is not in "
            "the current ADMIN_CONFIG_ENC_KEYS — add the old key back to decrypt."
        )
    from cryptography.fernet import InvalidToken  # type: ignore

    try:
        return f.decrypt(raw.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("ciphertext cannot be decrypted with the configured keys") from e


def rotate_to_primary(ciphertext: str) -> Tuple[str, bool]:
    """Re-encrypt with the current primary key if it is behind. For key rotation."""
    if not ciphertext.startswith(f"{_PREFIX}."):
        return ciphertext, False
    _, kid, _ = ciphertext.split(".", 2)
    if kid == _primary_key_id():
        return ciphertext, False
    value = decrypt_secret(ciphertext)
    new_ct, _ = encrypt_secret(value)
    return new_ct, True


def decrypt_to_masked(ciphertext: str) -> str:
    """Return the masked display form of a stored ciphertext (safe for UI)."""
    if not ciphertext:
        return ""
    from .credential_service import mask_secret

    return mask_secret(decrypt_secret(ciphertext))
