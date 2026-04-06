"""Tests for InstallationStore — local file backend, encryption, and IBM credential fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from integration.store import InstallationStore, _encrypt_record, _decrypt_record


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

def test_upsert_and_get(tmp_path: Path) -> None:
    store = InstallationStore(tmp_path / "store.json")
    record = store.upsert_installation(installation_id="ins_1", access_token="tok_abc")
    assert record["installation_id"] == "ins_1"
    assert record["access_token"] == "tok_abc"

    fetched = store.get_installation("ins_1")
    assert fetched is not None
    assert fetched["access_token"] == "tok_abc"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = InstallationStore(tmp_path / "store.json")
    assert store.get_installation("does_not_exist") is None


def test_delete_removes_record(tmp_path: Path) -> None:
    store = InstallationStore(tmp_path / "store.json")
    store.upsert_installation(installation_id="ins_1", access_token="tok")
    assert store.delete_installation("ins_1") is True
    assert store.get_installation("ins_1") is None


def test_delete_missing_returns_false(tmp_path: Path) -> None:
    store = InstallationStore(tmp_path / "store.json")
    assert store.delete_installation("nope") is False


def test_upsert_updates_existing(tmp_path: Path) -> None:
    store = InstallationStore(tmp_path / "store.json")
    store.upsert_installation(installation_id="ins_1", access_token="tok_old")
    store.upsert_installation(installation_id="ins_1", access_token="tok_new")
    record = store.get_installation("ins_1")
    assert record["access_token"] == "tok_new"


def test_installed_at_preserved_on_update(tmp_path: Path) -> None:
    store = InstallationStore(tmp_path / "store.json")
    r1 = store.upsert_installation(installation_id="ins_1", access_token="tok")
    r2 = store.upsert_installation(installation_id="ins_1", access_token="tok2")
    assert r1["installed_at"] == r2["installed_at"]


# ---------------------------------------------------------------------------
# IBM credential fields
# ---------------------------------------------------------------------------

def test_ibm_credentials_stored_and_retrieved(tmp_path: Path) -> None:
    store = InstallationStore(tmp_path / "store.json")
    store.upsert_installation(
        installation_id="ins_1",
        access_token="tok",
        ibm_cloud_api_key="my-api-key",
        ibm_code_engine_project_id="proj-123",
        ibm_registry_secret="icr-secret",
        ibm_cloud_region="eu-gb",
        ibm_icr_namespace="my-namespace",
    )
    record = store.get_installation("ins_1")
    assert record["ibm_cloud_api_key"] == "my-api-key"
    assert record["ibm_code_engine_project_id"] == "proj-123"
    assert record["ibm_registry_secret"] == "icr-secret"
    assert record["ibm_cloud_region"] == "eu-gb"
    assert record["ibm_icr_namespace"] == "my-namespace"


def test_ibm_credentials_preserved_across_token_refresh(tmp_path: Path) -> None:
    """Updating access_token should not wipe IBM credentials."""
    store = InstallationStore(tmp_path / "store.json")
    store.upsert_installation(
        installation_id="ins_1",
        access_token="tok_old",
        ibm_cloud_api_key="my-api-key",
        ibm_code_engine_project_id="proj-123",
        ibm_registry_secret="icr-secret",
    )
    store.upsert_installation(installation_id="ins_1", access_token="tok_new")
    record = store.get_installation("ins_1")
    assert record["access_token"] == "tok_new"
    assert record["ibm_cloud_api_key"] == "my-api-key"
    assert record["ibm_code_engine_project_id"] == "proj-123"


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip(monkeypatch) -> None:
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STORE_ENCRYPTION_KEY", key)

    record = {"ibm_cloud_api_key": "secret-key", "access_token": "tok", "other": "plain"}
    encrypted = _encrypt_record(record)

    assert encrypted["ibm_cloud_api_key"] != "secret-key"
    assert encrypted["access_token"] != "tok"
    assert encrypted["other"] == "plain"

    decrypted = _decrypt_record(encrypted)
    assert decrypted["ibm_cloud_api_key"] == "secret-key"
    assert decrypted["access_token"] == "tok"
    assert decrypted["other"] == "plain"


def test_no_encryption_when_key_not_set(monkeypatch) -> None:
    monkeypatch.delenv("STORE_ENCRYPTION_KEY", raising=False)
    record = {"ibm_cloud_api_key": "secret-key", "access_token": "tok"}
    assert _encrypt_record(record) == record
    assert _decrypt_record(record) == record


def test_store_encrypts_on_disk(tmp_path: Path, monkeypatch) -> None:
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STORE_ENCRYPTION_KEY", key)

    store = InstallationStore(tmp_path / "store.json")
    store.upsert_installation(
        installation_id="ins_1",
        access_token="tok_plaintext",
        ibm_cloud_api_key="super-secret",
    )

    # Read the raw file — sensitive values must not appear in plaintext
    raw = (tmp_path / "store.json").read_text()
    assert "tok_plaintext" not in raw
    assert "super-secret" not in raw

    # But get_installation should return decrypted values
    record = store.get_installation("ins_1")
    assert record["access_token"] == "tok_plaintext"
    assert record["ibm_cloud_api_key"] == "super-secret"


def test_decrypt_tolerates_plaintext_values(monkeypatch) -> None:
    """Migration case: record written without encryption should still be readable."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STORE_ENCRYPTION_KEY", key)

    record = {"ibm_cloud_api_key": "plaintext-not-encrypted", "access_token": "tok"}
    # _decrypt_record should leave values intact if they can't be decrypted
    result = _decrypt_record(record)
    assert result["ibm_cloud_api_key"] == "plaintext-not-encrypted"
