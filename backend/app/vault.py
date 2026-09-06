"""Encrypted credential vault. Secrets never appear in list payloads."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.crypto import decrypt, encrypt

VAULT_NAME = "vault.json"


class VaultError(ValueError):
    pass


def vault_path(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / VAULT_NAME


def _load(cache_dir: str | Path) -> dict[str, Any]:
    path = vault_path(cache_dir)
    if not path.is_file():
        return {"version": 1, "credentials": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "credentials": []}
    if not isinstance(data, dict):
        return {"version": 1, "credentials": []}
    rows = data.get("credentials")
    if not isinstance(rows, list):
        data["credentials"] = []
    return data


def _save(cache_dir: str | Path, data: dict[str, Any]) -> None:
    path = vault_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _models(row: dict[str, Any]) -> list[str]:
    raw = row.get("models")
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw if item]
    single = str(row.get("model") or "")
    return [single] if single else []


def _secret_hint(cache_dir: str | Path, row: dict[str, Any]) -> str:
    if not row.get("secret"):
        return ""
    secret = decrypt(cache_dir, row.get("secret"))
    if not secret:
        return ""
    shown = secret[:8]
    return f"{shown}{'•' * max(0, len(secret) - len(shown))}"


def _public(row: dict[str, Any], cache_dir: str | Path | None = None) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "providerId": row.get("providerId"),
        "model": row.get("model") or "",
        "models": _models(row),
        "label": row.get("label") or "",
        "kind": row.get("kind") or "key",
        "grants": list(row.get("grants") or []),
        "enabled": row.get("enabled", True) is not False,
        "createdAt": row.get("createdAt"),
        "hasSecret": bool(row.get("secret")),
        "secretHint": _secret_hint(cache_dir, row) if cache_dir else "",
    }


def first_secret(cache_dir: str | Path, provider_id: str) -> str:
    for row in _load(cache_dir)["credentials"]:
        if row.get("providerId") != provider_id or row.get("enabled", True) is False:
            continue
        secret = decrypt(cache_dir, row.get("secret"))
        if secret:
            return secret
    return ""


def list_credentials(cache_dir: str | Path) -> list[dict[str, Any]]:
    return [_public(row, cache_dir) for row in _load(cache_dir)["credentials"]]


def get_credential(cache_dir: str | Path, cred_id: str) -> dict[str, Any] | None:
    for row in _load(cache_dir)["credentials"]:
        if row.get("id") == cred_id:
            return row
    return None


def find_granted(cache_dir: str | Path, provider_id: str, consumer_id: str) -> dict[str, Any] | None:
    for row in _load(cache_dir)["credentials"]:
        if row.get("providerId") != provider_id or row.get("enabled", True) is False:
            continue
        if consumer_id in (row.get("grants") or []):
            return row
    return None


def resolve_secret(cache_dir: str | Path, provider_id: str, consumer_id: str = "", api_key: str = "") -> str:
    local = str(api_key or "").strip()
    if local:
        return local
    if consumer_id:
        row = find_granted(cache_dir, provider_id, consumer_id)
        if not row:
            return ""
        secret = decrypt(cache_dir, row.get("secret"))
        if secret:
            return secret
        from app.oauth import read_session

        session = read_session(cache_dir, provider_id) or {}
        return str(session.get("access_token") or "")
    return first_secret(cache_dir, provider_id)


def _overlap(rows: list[dict[str, Any]], provider_id: str, grants: list[str], skip_id: str = "") -> str | None:
    wanted = {item for item in grants if item}
    if not wanted:
        return None
    for row in rows:
        if row.get("id") == skip_id:
            continue
        if row.get("providerId") != provider_id:
            continue
        hit = wanted.intersection(row.get("grants") or [])
        if hit:
            return sorted(hit)[0]
    return None


def upsert_credential(
    cache_dir: str | Path,
    *,
    cred_id: str = "",
    provider_id: str,
    label: str,
    kind: str = "key",
    grants: list[str] | None = None,
    secret: str = "",
    model: str = "",
    models: list[str] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    provider_id = str(provider_id or "").strip()
    grants = [str(item).strip() for item in (grants or []) if str(item).strip()]
    data = _load(cache_dir)
    rows: list[dict[str, Any]] = data["credentials"]
    existing = next((row for row in rows if row.get("id") == cred_id), None) if cred_id else None
    clash = _overlap(rows, provider_id, grants, skip_id=str((existing or {}).get("id") or ""))
    if clash:
        raise VaultError(f"{clash} already has a {provider_id} key")
    if existing:
        existing["label"] = label or existing.get("label") or ""
        existing["kind"] = kind or existing.get("kind") or "key"
        existing["grants"] = grants
        if enabled is not None:
            existing["enabled"] = bool(enabled)
        if models is not None:
            picked = [str(item) for item in models if item]
            existing["models"] = picked
            existing["model"] = picked[0] if picked else ""
        if secret.strip():
            existing["secret"] = encrypt(cache_dir, secret.strip())
        _save(cache_dir, data)
        return _public(existing, cache_dir)
    row = {
        "id": cred_id or uuid4().hex[:16],
        "providerId": provider_id,
        "label": label or "Key",
        "kind": kind or "key",
        "grants": grants,
        "enabled": True if enabled is None else bool(enabled),
        "model": (models or [model] or [""])[0] if (models or model) else "",
        "models": [str(item) for item in (models or []) if item] or ([model] if model else []),
        "createdAt": int(time.time()),
        "secret": encrypt(cache_dir, secret.strip()) if secret.strip() else None,
    }
    rows.append(row)
    _save(cache_dir, data)
    return _public(row, cache_dir)


def delete_credential(cache_dir: str | Path, cred_id: str) -> bool:
    data = _load(cache_dir)
    before = len(data["credentials"])
    data["credentials"] = [row for row in data["credentials"] if row.get("id") != cred_id]
    if len(data["credentials"]) == before:
        return False
    _save(cache_dir, data)
    return True
