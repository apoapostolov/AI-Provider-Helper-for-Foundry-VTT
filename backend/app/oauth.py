"""Device-code OAuth for OpenAI Codex and xAI SuperGrok/Premium.

Token files live under cache_dir/oauth/. Never log or return token values.
Flows verified against Hermes auth.py and Lingarr XaiOAuthSessionService.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_ISSUER = "https://auth.openai.com"
CODEX_USERCODE_URL = f"{CODEX_ISSUER}/api/accounts/deviceauth/usercode"
CODEX_POLL_URL = f"{CODEX_ISSUER}/api/accounts/deviceauth/token"
CODEX_TOKEN_URL = f"{CODEX_ISSUER}/oauth/token"
CODEX_VERIFY_URL = f"{CODEX_ISSUER}/codex/device"
CODEX_REDIRECT = f"{CODEX_ISSUER}/deviceauth/callback"

XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_SCOPE = "openid profile email offline_access grok-cli:access api:access"
XAI_DEVICE_URL = "https://auth.x.ai/oauth2/device/code"
XAI_TOKEN_URL = "https://auth.x.ai/oauth2/token"
XAI_VERIFY_URL = "https://accounts.x.ai/oauth2/device"
XAI_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

OAUTH_PROVIDERS = frozenset({"openai-codex", "xai-oauth"})

_pending: dict[str, dict[str, Any]] = {}


def oauth_dir(cache_dir: str | Path) -> Path:
    path = Path(cache_dir) / "oauth"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _token_path(cache_dir: str | Path, provider: str) -> Path:
    return oauth_dir(cache_dir) / f"{provider}.json"


def _write_tokens(cache_dir: str | Path, provider: str, payload: dict[str, Any]) -> None:
    path = _token_path(cache_dir, provider)
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_CHAT_MODEL = "gpt-5.5"
CODEX_IMAGE_MODEL = "gpt-image-2"


def chatgpt_account_id(token: str) -> str:
    """Read chatgpt_account_id from an unverified JWT payload."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return ""
        pad = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        auth = payload.get("https://api.openai.com/auth")
        if isinstance(auth, dict):
            return str(auth.get("chatgpt_account_id") or "").strip()
    except Exception:
        return ""
    return ""


async def ensure_fresh_session(http: httpx.AsyncClient, cache_dir: str | Path, provider: str) -> dict[str, Any]:
    sess = read_session(cache_dir, provider) or {}
    if not sess:
        return {}
    expires = float(sess.get("expires_at") or 0)
    if sess.get("access_token") and expires > time.time() + 60:
        return sess
    refresh = str(sess.get("refresh_token") or "")
    if not refresh:
        return sess
    if provider == "openai-codex":
        response = await http.post(
            CODEX_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CODEX_CLIENT_ID,
                "refresh_token": refresh,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    else:
        response = await http.post(
            XAI_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": XAI_CLIENT_ID,
                "refresh_token": refresh,
            },
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        return sess
    try:
        data = response.json()
    except ValueError:
        return sess
    access = str(data.get("access_token") or "")
    if not access:
        return sess
    expires_in = int(data.get("expires_in") or 3600)
    payload = {
        **sess,
        "access_token": access,
        "refresh_token": data.get("refresh_token") or refresh,
        "expires_at": time.time() + expires_in,
    }
    _write_tokens(cache_dir, provider, payload)
    return payload


def read_session(cache_dir: str | Path, provider: str) -> dict[str, Any] | None:
    path = _token_path(cache_dir, provider)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not data.get("access_token"):
        return None
    return data


def session_status(cache_dir: str | Path, provider: str) -> dict[str, Any]:
    session = read_session(cache_dir, provider)
    if not session:
        return {"connected": False}
    return {
        "connected": True,
        "expires_at": session.get("expires_at"),
    }


def disconnect(cache_dir: str | Path, provider: str) -> None:
    path = _token_path(cache_dir, provider)
    if path.is_file():
        path.unlink()


def _require_provider(provider: str) -> None:
    if provider not in OAUTH_PROVIDERS:
        raise ValueError(f"OAuth is not supported for {provider}")


async def start_flow(provider: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    _require_provider(provider)
    own = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    try:
        if provider == "openai-codex":
            return await _start_codex(http)
        return await _start_xai(http)
    finally:
        if own:
            await http.aclose()


async def _start_codex(http: httpx.AsyncClient) -> dict[str, Any]:
    response = await http.post(
        CODEX_USERCODE_URL,
        json={"client_id": CODEX_CLIENT_ID},
        headers={"Content-Type": "application/json"},
    )
    if response.status_code >= 400:
        return {"ok": False, "error": f"HTTP {response.status_code}"}
    data = response.json()
    user_code = data.get("user_code") or ""
    device_auth_id = data.get("device_auth_id") or ""
    if not user_code or not device_auth_id:
        return {"ok": False, "error": "Device code response incomplete"}
    flow_id = secrets.token_hex(12)
    interval = max(3, int(data.get("interval") or 5))
    _pending[flow_id] = {
        "provider": "openai-codex",
        "kind": "codex",
        "user_code": user_code,
        "device_auth_id": device_auth_id,
        "interval": interval,
        "expires_at": time.time() + 15 * 60,
    }
    return {
        "ok": True,
        "flow_id": flow_id,
        "user_code": user_code,
        "verification_uri": CODEX_VERIFY_URL,
        "verification_uri_complete": CODEX_VERIFY_URL,
        "interval_seconds": interval,
    }


async def _start_xai(http: httpx.AsyncClient) -> dict[str, Any]:
    response = await http.post(
        XAI_DEVICE_URL,
        data={"client_id": XAI_CLIENT_ID, "scope": XAI_SCOPE},
        headers={"Accept": "application/json"},
    )
    if response.status_code >= 400:
        return {"ok": False, "error": f"HTTP {response.status_code}"}
    data = response.json()
    device_code = data.get("device_code") or data.get("deviceCode") or ""
    user_code = data.get("user_code") or data.get("userCode") or ""
    if not device_code or not user_code:
        return {"ok": False, "error": "Device code response incomplete"}
    interval = max(3, int(data.get("interval") or 5))
    expires_in = max(60, int(data.get("expires_in") or data.get("expiresIn") or 1800))
    flow_id = secrets.token_hex(12)
    _pending[flow_id] = {
        "provider": "xai-oauth",
        "kind": "xai",
        "device_code": device_code,
        "interval": interval,
        "expires_at": time.time() + expires_in,
    }
    verify = (
        data.get("verification_uri")
        or data.get("verificationUri")
        or XAI_VERIFY_URL
    )
    verify_complete = data.get("verification_uri_complete") or data.get("verificationUriComplete")
    return {
        "ok": True,
        "flow_id": flow_id,
        "user_code": user_code,
        "verification_uri": verify,
        "verification_uri_complete": verify_complete or verify,
        "interval_seconds": interval,
    }


async def poll_flow(
    provider: str,
    flow_id: str,
    cache_dir: str | Path,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    _require_provider(provider)
    pending = _pending.get(flow_id)
    if not pending or pending.get("provider") != provider:
        return {"status": "expired", "message": "Unknown or expired login"}
    if pending["expires_at"] <= time.time():
        _pending.pop(flow_id, None)
        return {"status": "expired", "message": "The device code expired. Start again."}

    own = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    try:
        if pending["kind"] == "codex":
            return await _poll_codex(http, pending, flow_id, cache_dir)
        return await _poll_xai(http, pending, flow_id, cache_dir)
    finally:
        if own:
            await http.aclose()


async def _poll_codex(
    http: httpx.AsyncClient,
    pending: dict[str, Any],
    flow_id: str,
    cache_dir: str | Path,
) -> dict[str, Any]:
    response = await http.post(
        CODEX_POLL_URL,
        json={
            "device_auth_id": pending["device_auth_id"],
            "user_code": pending["user_code"],
        },
        headers={"Content-Type": "application/json"},
    )
    if response.status_code in {403, 404}:
        return {"status": "pending", "interval_seconds": pending["interval"]}
    if response.status_code >= 400:
        return {"status": "error", "message": f"HTTP {response.status_code}"}
    data = response.json()
    authorization_code = data.get("authorization_code") or ""
    code_verifier = data.get("code_verifier") or ""
    if not authorization_code or not code_verifier:
        return {"status": "pending", "interval_seconds": pending["interval"]}

    token_resp = await http.post(
        CODEX_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": CODEX_REDIRECT,
            "client_id": CODEX_CLIENT_ID,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if token_resp.status_code >= 400:
        return {"status": "error", "message": f"Token exchange HTTP {token_resp.status_code}"}
    tokens = token_resp.json()
    access = tokens.get("access_token") or ""
    if not access:
        return {"status": "error", "message": "Token exchange returned no access token"}
    expires_in = int(tokens.get("expires_in") or 3600)
    _write_tokens(
        cache_dir,
        "openai-codex",
        {
            "access_token": access,
            "refresh_token": tokens.get("refresh_token") or "",
            "expires_at": time.time() + expires_in,
            "auth_mode": "chatgpt",
        },
    )
    _pending.pop(flow_id, None)
    return {"status": "connected"}


async def _poll_xai(
    http: httpx.AsyncClient,
    pending: dict[str, Any],
    flow_id: str,
    cache_dir: str | Path,
) -> dict[str, Any]:
    response = await http.post(
        XAI_TOKEN_URL,
        data={
            "grant_type": XAI_DEVICE_GRANT,
            "device_code": pending["device_code"],
            "client_id": XAI_CLIENT_ID,
        },
        headers={"Accept": "application/json"},
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.is_success and data.get("access_token"):
        expires_in = int(data.get("expires_in") or 21600)
        _write_tokens(
            cache_dir,
            "xai-oauth",
            {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token") or "",
                "expires_at": time.time() + expires_in,
            },
        )
        _pending.pop(flow_id, None)
        return {"status": "connected"}

    error = data.get("error") or ""
    if error in {"authorization_pending", "slow_down"}:
        extra = 5 if error == "slow_down" else 0
        return {"status": "pending", "interval_seconds": pending["interval"] + extra}
    if error in {"expired_token", "expired"}:
        _pending.pop(flow_id, None)
        return {"status": "expired", "message": "The device code expired. Start again."}
    if error in {"access_denied", "authorization_denied"}:
        _pending.pop(flow_id, None)
        return {"status": "denied", "message": data.get("error_description") or "Login was denied."}
    if response.status_code >= 400 and not error:
        return {"status": "pending", "interval_seconds": pending["interval"]}
    return {"status": "error", "message": data.get("error_description") or error or "Login failed"}


def codex_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "text/event-stream",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "codex_cli_rs/0.0.0 (AI Provider Library)",
        "originator": "codex_cli_rs",
    }
    account = chatgpt_account_id(token)
    if account:
        headers["ChatGPT-Account-ID"] = account
    return headers


def extract_codex_image(value: Any) -> str:
    found = ""

    def walk(node: Any) -> None:
        nonlocal found
        if isinstance(node, dict):
            if node.get("type") == "image_generation_call" and isinstance(node.get("result"), str) and node["result"]:
                found = node["result"]
            partial = node.get("partial_image_b64")
            if isinstance(partial, str) and partial:
                found = partial
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found


def _openai_size(width: int, height: int) -> str:
    ratio = (width or 1) / (height or 1)
    if ratio > 1.15:
        return "1536x1024"
    if ratio < 0.87:
        return "1024x1536"
    return "1024x1024"


def _codex_quality(model: str) -> str:
    ident = model or ""
    if "low" in ident or ident == "gpt-image-1":
        return "low"
    if "1.5" in ident or "medium" in ident:
        return "medium"
    return "high"


def _codex_background(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"transparent", "auto"}:
        return raw
    return "opaque"


async def generate_codex_image(
    token: str,
    prompt: str,
    width: int,
    height: int,
    model: str = "gpt-image-2",
    images: list[str] | None = None,
    background: str = "opaque",
    size: str = "",
) -> str:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for img in images or []:
        if isinstance(img, str) and img.startswith("data:image/"):
            content.append({"type": "input_image", "image_url": img})
    wanted = _codex_background(background)
    attempts = [wanted] if wanted == "opaque" else [wanted, "opaque"]
    last_error: Exception | None = None
    for bg in attempts:
        payload = {
            "model": CODEX_CHAT_MODEL,
            "store": False,
            "instructions": (
                "You are an assistant that must fulfill image generation and image "
                "editing requests by using the image_generation tool when provided."
            ),
            "input": [{"type": "message", "role": "user", "content": content}],
            "tools": [{
                "type": "image_generation",
                "model": CODEX_IMAGE_MODEL,
                "size": size or _openai_size(width, height),
                "quality": _codex_quality(model),
                "output_format": "png",
                "background": bg,
                "partial_images": 1,
            }],
            "stream": True,
        }
        try:
            found = await _stream_codex_image(token, payload)
        except RuntimeError as exc:
            last_error = exc
            if bg != "opaque" and "Transparent background is not supported" in str(exc):
                continue
            raise
        if found:
            return found
    if last_error:
        raise last_error
    raise RuntimeError("Codex returned no image")


async def _stream_codex_image(token: str, payload: dict[str, Any]) -> str:
    found = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as http:
        async with http.stream(
            "POST",
            CODEX_RESPONSES_URL,
            headers=codex_headers(token),
            json=payload,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(short_provider_error(response.status_code, body, "chatgpt.com"))
            buf = ""
            async for chunk in response.aiter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    data_lines = [
                        line[5:].lstrip() for line in block.split("\n") if line.startswith("data:")
                    ]
                    raw = "\n".join(data_lines).strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    hit = extract_codex_image(event)
                    if hit:
                        found = hit
    return found


def _codex_content(content: Any, role: str = "user") -> list[dict[str, Any]]:
    text_type = "output_text" if role == "assistant" else "input_text"
    if isinstance(content, str):
        return [{"type": text_type, "text": content}]
    parts: list[dict[str, Any]] = []
    if not isinstance(content, list):
        text = str(content or "")
        return [{"type": text_type, "text": text}] if text else []
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        if kind in {"text", "input_text", "output_text"}:
            parts.append({"type": text_type, "text": str(item.get("text") or "")})
            continue
        if kind in {"image_url", "input_image"}:
            url = item.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            if url:
                parts.append({"type": "input_image", "image_url": str(url)})
    return parts


def messages_to_codex_input(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions = ""
    rows: list[dict[str, Any]] = []
    for msg in messages or []:
        role = str(msg.get("role") or "user")
        parts = _codex_content(msg.get("content"), role)
        if role == "system":
            text = " ".join(part.get("text") or "" for part in parts if part.get("type") == "input_text")
            instructions = f"{instructions} {text}".strip() if instructions else text.strip()
            continue
        if not parts:
            continue
        rows.append({
            "type": "message",
            "role": "assistant" if role == "assistant" else "user",
            "content": parts,
        })
    return instructions, rows


def extract_codex_text(event: Any) -> str:
    if not isinstance(event, dict):
        return ""
    etype = str(event.get("type") or "")
    if etype.endswith("output_text.delta"):
        return str(event.get("delta") or "")
    if isinstance(event.get("output_text"), str) and etype.endswith("completed"):
        return event["output_text"]
    texts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") in {"output_text", "text"} and isinstance(node.get("text"), str):
                texts.append(node["text"])
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    if etype in {"response.completed", "response.output_item.done"}:
        walk(event)
    return "".join(texts)


async def generate_codex_chat(token: str, messages: list[dict[str, Any]], model: str = "", extras: dict[str, Any] | None = None) -> str:
    instructions, rows = messages_to_codex_input(messages)
    if not rows:
        raise RuntimeError("No messages")
    payload: dict[str, Any] = {
        "model": model or CODEX_CHAT_MODEL,
        "store": False,
        "input": rows,
        "stream": True,
    }
    if instructions:
        payload["instructions"] = instructions
    reasoning = (extras or {}).get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        payload["reasoning"] = {"effort": str(reasoning["effort"])}
    deltas: list[str] = []
    final = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=30.0)) as http:
        async with http.stream(
            "POST",
            CODEX_RESPONSES_URL,
            headers=codex_headers(token),
            json=payload,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(short_provider_error(response.status_code, body, "chatgpt.com"))
            buf = ""
            async for chunk in response.aiter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    data_lines = [
                        line[5:].lstrip() for line in block.split("\n") if line.startswith("data:")
                    ]
                    raw = "\n".join(data_lines).strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    etype = str(event.get("type") or "")
                    if etype.endswith("output_text.delta"):
                        deltas.append(str(event.get("delta") or ""))
                        continue
                    hit = extract_codex_text(event)
                    if hit:
                        final = hit
    text = "".join(deltas) or final
    if not text.strip():
        raise RuntimeError("Codex returned no text")
    return text


def short_provider_error(status: int, body: str, host: str = "") -> str:
    sample = (body or "").lstrip()
    if sample[:15].lower().startswith("<!doctype") or sample[:6].lower().startswith("<html") or "<html" in sample[:400].lower():
        where = f" from {host}" if host else ""
        return f"HTTP {status} HTML{where}"
    return (body or f"HTTP {status}")[:400]
