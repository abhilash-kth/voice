"""Unit tests for credential encryption-at-rest and masking (no DB needed)."""
from __future__ import annotations

import os

import pytest

from app.services import crypto
from app.services.credential_service import mask_secret


@pytest.fixture(autouse=True)
def _env_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ADMIN_CONFIG_ENC_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("ADMIN_CONFIG_ENC_KEYS", raising=False)
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


def test_mask_secret_last4():
    assert mask_secret("sk-abc1234567890XYZ") == "************0XYZ"
    assert mask_secret("abcd") == "************abcd"
    assert mask_secret("") == ""


def test_round_trip():
    original = "sk-test-secret-987654321"
    ciphertext, masked = crypto.encrypt_secret(original)
    assert ciphertext.startswith("v1.v1.")
    assert masked.endswith("4321")
    assert original not in ciphertext
    assert original not in masked
    assert crypto.decrypt_secret(ciphertext) == original


def test_decrypt_with_unknown_key_id_fails(monkeypatch):
    ciphertext, _ = crypto.encrypt_secret("hello")
    crypto.reset_cache_for_tests()
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ADMIN_CONFIG_ENC_KEYS", "")
    monkeypatch.setenv("ADMIN_CONFIG_ENC_KEY", Fernet.generate_key().decode())
    with pytest.raises(Exception):
        crypto.decrypt_secret(ciphertext)


def test_key_rotation_decrypts_old_and_writes_new(monkeypatch):
    from cryptography.fernet import Fernet

    k1 = Fernet.generate_key().decode()
    k2 = Fernet.generate_key().decode()
    monkeypatch.setenv("ADMIN_CONFIG_ENC_KEYS", "")
    monkeypatch.setenv("ADMIN_CONFIG_ENC_KEY", k1)
    crypto.reset_cache_for_tests()
    old_ct, _ = crypto.encrypt_secret("rotation-value")

    # the old single key stays (id v1); the new map's LAST entry is primary.
    monkeypatch.setenv("ADMIN_CONFIG_ENC_KEYS", f'{{"k2": "{k2}"}}')
    crypto.reset_cache_for_tests()

    # old ciphertext still decrypts
    assert crypto.decrypt_secret(old_ct) == "rotation-value"
    # rotation re-encrypts under the new primary
    new_ct, changed = crypto.rotate_to_primary(old_ct)
    assert changed and new_ct.startswith("v1.k2.")
    assert crypto.decrypt_secret(new_ct) == "rotation-value"


def test_jwt_fallback_warning_derives_key(monkeypatch):
    monkeypatch.delenv("ADMIN_CONFIG_ENC_KEY", raising=False)
    monkeypatch.delenv("ADMIN_CONFIG_ENC_KEYS", raising=False)
    crypto.reset_cache_for_tests()
    ct, _ = crypto.encrypt_secret("dev-value")
    assert crypto.decrypt_secret(ct) == "dev-value"
