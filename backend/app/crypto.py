"""AES-256-GCM helpers. Master key lives on disk, mode 0600. Never log it."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_NAME = "master.key"


def master_path(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / MASTER_NAME


def load_or_create_master(cache_dir: str | Path) -> bytes:
    path = master_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        key = path.read_bytes()
        if len(key) == 32:
            return key
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def encrypt(cache_dir: str | Path, plaintext: str) -> dict[str, str]:
    key = load_or_create_master(cache_dir)
    nonce = secrets.token_bytes(12)
    blob = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return {
        "v": "1",
        "n": nonce.hex(),
        "c": blob.hex(),
    }


def decrypt(cache_dir: str | Path, payload: dict | None) -> str:
    if not payload or payload.get("v") != "1":
        return ""
    key = load_or_create_master(cache_dir)
    nonce = bytes.fromhex(str(payload.get("n") or ""))
    blob = bytes.fromhex(str(payload.get("c") or ""))
    try:
        return AESGCM(key).decrypt(nonce, blob, None).decode("utf-8")
    except Exception:
        return ""
