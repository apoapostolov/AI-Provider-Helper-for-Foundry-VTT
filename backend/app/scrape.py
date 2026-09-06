"""Public models.dev catalog. Fail quiet."""

from __future__ import annotations

from typing import Any

import httpx

from app.capabilities import capabilities_from_architecture

MODELS_DEV = "https://models.dev/api.json"

DEV_TO_OURS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gemini",
    "xai": "xai",
    "mistral": "mistral",
    "deepseek": "deepseek",
    "alibaba": "qwen",
    "zai": "zai",
    "openrouter": "openrouter",
}


def parse_models_dev(payload: object) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for dev_id, ours in DEV_TO_OURS.items():
        block = payload.get(dev_id)
        if not isinstance(block, dict):
            continue
        raw = block.get("models")
        if isinstance(raw, dict):
            items = list(raw.values())
        elif isinstance(raw, list):
            items = raw
        else:
            continue
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id") or "")
            if not mid:
                continue
            modalities = item.get("modalities") if isinstance(item.get("modalities"), dict) else {}
            caps = capabilities_from_architecture({
                "input_modalities": modalities.get("input"),
                "output_modalities": modalities.get("output"),
            })
            cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
            limit = item.get("limit") if isinstance(item.get("limit"), dict) else {}
            rows.append({
                "id": mid,
                "label": str(item.get("name") or mid),
                "capabilities": caps,
                "cost": {
                    key: cost[src]
                    for key, src in (("prompt", "input"), ("completion", "output"), ("cached", "cache_read"))
                    if cost.get(src) is not None
                } or None,
                "contextLength": limit.get("context"),
                "live": True,
                "source": "models.dev",
            })
        if rows:
            out[ours] = rows
    if out.get("openai"):
        out.setdefault("openai-codex", list(out["openai"]))
    if out.get("xai"):
        out.setdefault("xai-oauth", list(out["xai"]))
    return out


def flatten_models_dev(by_provider: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for pid, rows in by_provider.items():
        for row in rows:
            cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
            flat.append({
                "id": row.get("id"),
                "provider": pid,
                "costIn": cost.get("prompt"),
                "costOut": cost.get("completion"),
                "costInCached": cost.get("cached"),
                "source": "models.dev",
            })
    return flat


async def fetch_models_dev(client: httpx.AsyncClient | None = None) -> dict[str, list[dict[str, Any]]]:
    own = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    try:
        response = await http.get(MODELS_DEV, headers={"Accept": "application/json"})
    except httpx.RequestError:
        return {}
    finally:
        if own:
            await http.aclose()
    if response.status_code >= 400:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    return parse_models_dev(payload)
