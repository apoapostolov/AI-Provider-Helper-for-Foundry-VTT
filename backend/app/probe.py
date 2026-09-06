from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.capabilities import capabilities_from_architecture, has_capability
from app.catalog import DEFAULT_ENDPOINTS
from app.oauth import OAUTH_PROVIDERS, chatgpt_account_id, read_session
from app.schemas import ProbeRequest


def _headers(req: ProbeRequest, token: str = "") -> dict[str, str]:
    key = token or req.api_key
    if not key:
        return {}
    if req.provider == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    headers = {"Authorization": f"Bearer {key}"}
    if req.provider == "openai-codex":
        headers["User-Agent"] = "codex-cli"
        account_id = chatgpt_account_id(key)
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id
    return headers


def _resolve_token(req: ProbeRequest, cache_dir: str | Path | None) -> str:
    if req.api_key:
        return req.api_key
    if cache_dir and req.provider in OAUTH_PROVIDERS:
        session = read_session(cache_dir, req.provider)
        return str((session or {}).get("access_token") or "")
    return ""


STATUS_REASON: dict[int, str] = {
    400: "Bad request",
    401: "Unauthorized",
    402: "Payment required",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    408: "Timeout",
    409: "Conflict",
    410: "Gone",
    413: "Payload too large",
    414: "URI too long",
    415: "Unsupported media type",
    422: "Unprocessable",
    425: "Too early",
    429: "Rate limited",
    451: "Unavailable for legal reasons",
    500: "Internal server error",
    501: "Not implemented",
    502: "Bad gateway",
    503: "Overloaded",
    504: "Gateway timeout",
    507: "Insufficient storage",
    520: "Web server error",
    521: "Server down",
    522: "Connection timed out",
    523: "Origin unreachable",
    524: "Timeout",
    529: "Overloaded",
}


def _status_reason(code: int) -> str:
    return STATUS_REASON.get(code, "") or ""


def _normalize_models(raw: list, capability: str = "") -> list[dict[str, str]]:
    models: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            mid = str(item.get("id") or item.get("name") or "")
            label = str(item.get("name") or mid)
            arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else item
            caps = capabilities_from_architecture(arch) if isinstance(arch, dict) else []
        else:
            mid = str(item)
            label = mid
            caps = []
        if not mid:
            continue
        if capability and caps and not has_capability(caps, capability):
            continue
        models.append({"id": mid, "label": label, "capabilities": caps})
    return models[:120]


async def probe_provider(
    req: ProbeRequest,
    client: httpx.AsyncClient | None = None,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    endpoint = (req.endpoint or DEFAULT_ENDPOINTS.get(req.provider, "")).rstrip("/")
    if not endpoint:
        return {"ok": False, "error": "No endpoint", "models": []}

    token = _resolve_token(req, cache_dir)
    url = (
        "https://chatgpt.com/backend-api/wham/usage"
        if req.provider == "openai-codex"
        else f"{endpoint}/models"
    )
    if req.provider == "gemini" and token and "generativelanguage.googleapis.com" in endpoint and "/openai" not in endpoint:
        url = f"{endpoint}/models?key={token}"

    own = client is None
    http = client or httpx.AsyncClient(timeout=12.0)
    try:
        response = await http.get(url, headers=_headers(req, token))
    except httpx.RequestError:
        return {"ok": False, "status": 0, "error": "Unreachable", "models": []}
    finally:
        if own:
            await http.aclose()

    if response.status_code >= 400:
        reason = _status_reason(response.status_code)
        message = f"HTTP {response.status_code}" + (f" {reason}" if reason else "")
        return {
            "ok": False,
            "status": response.status_code,
            "error": message,
            "models": [],
        }

    if req.provider in OAUTH_PROVIDERS and not req.refresh:
        return {"ok": True, "detail": "OAuth session is valid", "models": []}
    if req.provider == "openai-codex":
        return {"ok": True, "detail": "OAuth session is valid", "models": []}

    try:
        data = response.json()
    except ValueError:
        return {"ok": True, "detail": "Answered, no JSON catalog", "models": []}

    raw = data.get("data") if isinstance(data, dict) else data
    if raw is None and isinstance(data, dict):
        raw = data.get("models", [])
    if not isinstance(raw, list):
        raw = []
    models = _normalize_models(raw, req.capability)
    return {"ok": True, "detail": f"{len(models)} models", "models": models}
