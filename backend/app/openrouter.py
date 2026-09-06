from __future__ import annotations

from typing import Any

import httpx

from app.capabilities import capabilities_from_architecture

OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"


async def fetch_openrouter_models(api_key: str = "", client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    own = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    try:
        response = await http.get(OPENROUTER_MODELS, headers=headers)
    except httpx.RequestError:
        return []
    finally:
        if own:
            await http.aclose()
    if response.status_code >= 400:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    raw = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return []
    models: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "")
        if not mid:
            continue
        arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        models.append({
            "id": mid,
            "label": str(item.get("name") or mid),
            "capabilities": capabilities_from_architecture(arch),
            "cost": {
                key: str(pricing[key])
                for key in ("prompt", "completion", "image", "request")
                if pricing.get(key) is not None
            },
            "contextLength": item.get("context_length") or item.get("contextLength"),
            "live": True,
            "source": "openrouter",
        })
    return models
