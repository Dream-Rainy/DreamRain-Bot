from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_CREDENTIALS_PATH = Path(__file__).resolve().parents[2] / "src/plugins/priconne/credentials.py"
_SPEC = importlib.util.spec_from_file_location("priconne_credentials_test_module", _CREDENTIALS_PATH)
credentials = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(credentials)

CredentialKeyError = credentials.CredentialKeyError
build_stored_account = credentials.build_stored_account
decrypt_password = credentials.decrypt_password
encrypt_password = credentials.encrypt_password
prepare_account_for_login = credentials.prepare_account_for_login
should_update_stored_account = credentials.should_update_stored_account


def test_priconne_password_encryption_roundtrip(monkeypatch):
    monkeypatch.setenv("PRICONNE_CREDENTIAL_KEY", "test-secret-key")
    monkeypatch.delenv("PRICONNE_CREDENTIAL_KEY_FILE", raising=False)

    encrypted = encrypt_password("plain-password")

    assert encrypted.startswith("v1:")
    assert "plain-password" not in encrypted
    assert decrypt_password(encrypted) == "plain-password"


def test_priconne_prepare_account_decrypts_password(monkeypatch):
    monkeypatch.setenv("PRICONNE_CREDENTIAL_KEY", "test-secret-key")
    monkeypatch.delenv("PRICONNE_CREDENTIAL_KEY_FILE", raising=False)
    encrypted = encrypt_password("plain-password")

    prepared = prepare_account_for_login({"account": "user", "password_encrypted": encrypted})

    assert prepared["password"] == "plain-password"


def test_priconne_build_stored_account_removes_plain_password(monkeypatch):
    monkeypatch.setenv("PRICONNE_CREDENTIAL_KEY", "test-secret-key")
    monkeypatch.delenv("PRICONNE_CREDENTIAL_KEY_FILE", raising=False)

    stored = build_stored_account(
        {"account": "user", "password": "plain-password", "platform": 2, "channel": 1},
        "uid-1",
        "access-key-1",
    )

    assert "password" not in stored
    assert stored["password_encrypted"].startswith("v1:")
    assert decrypt_password(stored["password_encrypted"]) == "plain-password"
    assert stored["uid"] == "uid-1"
    assert stored["access_key"] == "access-key-1"


def test_priconne_missing_key_blocks_new_encrypted_password(monkeypatch):
    monkeypatch.delenv("PRICONNE_CREDENTIAL_KEY", raising=False)
    monkeypatch.delenv("PRICONNE_CREDENTIAL_KEY_FILE", raising=False)

    with pytest.raises(CredentialKeyError):
        build_stored_account({"account": "user", "password": "plain-password"}, "uid-1", "access-key-1")


def test_priconne_should_update_plain_or_refreshed_account():
    assert should_update_stored_account({"password": "plain"}, "uid-1", "access-key-1")
    assert should_update_stored_account({"uid": "uid-1", "access_key": "old"}, "uid-1", "access-key-1")
    assert not should_update_stored_account({"uid": "uid-1", "access_key": "access-key-1"}, "uid-1", "access-key-1")
