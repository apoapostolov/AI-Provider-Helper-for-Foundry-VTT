from __future__ import annotations

from pathlib import Path

import pytest

from app.crypto import decrypt, encrypt
from app.vault import VaultError, find_granted, list_credentials, resolve_secret, upsert_credential


def test_empty_row_allowed(tmp_path: Path) -> None:
    row = upsert_credential(tmp_path, provider_id="", label="", grants=[], secret="")
    assert row["providerId"] == ""
    assert row["hasSecret"] is False
    listed = list_credentials(tmp_path)
    assert len(listed) == 1
    assert listed[0]["id"] == row["id"]


def test_encrypt_roundtrip(tmp_path: Path) -> None:
    blob = encrypt(tmp_path, "sk-test")
    assert "sk-test" not in str(blob)
    assert decrypt(tmp_path, blob) == "sk-test"


def test_overlap_rejected(tmp_path: Path) -> None:
    upsert_credential(tmp_path, provider_id="openai", label="A", grants=["hex-atlas-survey"], secret="aaa")
    with pytest.raises(VaultError):
        upsert_credential(tmp_path, provider_id="openai", label="B", grants=["hex-atlas-survey"], secret="bbb")


def test_two_keys_split_modules(tmp_path: Path) -> None:
    first = upsert_credential(tmp_path, provider_id="openai", label="Vision", grants=["hex-atlas-survey"], secret="aaabbbcccddd")
    second = upsert_credential(tmp_path, provider_id="openai", label="Tiles", grants=["imaginary-tiles"], secret="bbbcccdddeee")
    assert first["id"] != second["id"]
    assert resolve_secret(tmp_path, "openai", "hex-atlas-survey") == "aaabbbcccddd"
    assert resolve_secret(tmp_path, "openai", "imaginary-tiles") == "bbbcccdddeee"
    assert find_granted(tmp_path, "openai", "file-seeker") is None
    public = list_credentials(tmp_path)
    assert all("secret" not in row for row in public)
    assert all(row["hasSecret"] for row in public)
    assert first["secretHint"] == "aaabbbcc••••"


def test_resolve_secret_without_grant_uses_first_key(tmp_path: Path) -> None:
    upsert_credential(tmp_path, provider_id="deepseek", label="Wallet", grants=[], secret="sk-deepseek-test")
    assert resolve_secret(tmp_path, "deepseek", "") == "sk-deepseek-test"
    assert resolve_secret(tmp_path, "deepseek") == "sk-deepseek-test"


def test_disabled_credential_is_not_granted_or_resolved(tmp_path: Path) -> None:
    upsert_credential(
        tmp_path,
        provider_id="openai",
        label="Disabled",
        grants=["hex-atlas-survey"],
        secret="sk-disabled",
        enabled=False,
    )
    assert find_granted(tmp_path, "openai", "hex-atlas-survey") is None
    assert resolve_secret(tmp_path, "openai", "hex-atlas-survey") == ""
    assert resolve_secret(tmp_path, "openai") == ""
    assert list_credentials(tmp_path)[0]["enabled"] is False


def test_resolve_secret_uses_oauth_session(tmp_path: Path) -> None:
    row = upsert_credential(
        tmp_path,
        provider_id="openai-codex",
        label="Codex",
        kind="oauth",
        grants=["hex-atlas-survey"],
        secret="",
    )
    oauth = tmp_path / "oauth"
    oauth.mkdir()
    (oauth / "openai-codex.json").write_text(
        '{"access_token": "codex-access-token", "refresh_token": "r"}',
        encoding="utf-8",
    )
    assert resolve_secret(tmp_path, "openai-codex", "hex-atlas-survey") == "codex-access-token"
    assert resolve_secret(tmp_path, "openai-codex", "imaginary-tiles") == ""
    assert resolve_secret(tmp_path, "openai-codex", "file-seeker") == ""
    upsert_credential(
        tmp_path,
        cred_id=row["id"],
        provider_id="openai-codex",
        label="Codex",
        kind="oauth",
        grants=["hex-atlas-survey", "imaginary-tiles", "file-seeker"],
        secret="",
    )
    for consumer in ("hex-atlas-survey", "imaginary-tiles", "file-seeker"):
        assert resolve_secret(tmp_path, "openai-codex", consumer) == "codex-access-token"
