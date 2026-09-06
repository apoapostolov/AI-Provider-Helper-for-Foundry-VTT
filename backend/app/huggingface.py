from __future__ import annotations

from typing import Any

import httpx

from app.capabilities import capabilities_from_pipeline_tag

HF_MODELS = "https://huggingface.co/api/models"
HF_TAGS = (
    "image-text-to-text",
    "text-to-image",
    "image-to-image",
    "text-generation",
)


async def fetch_huggingface_models(
    token: str = "",
    limit: int = 40,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    own = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    models: list[dict[str, Any]] = []
    try:
        for tag in HF_TAGS:
            try:
                response = await http.get(
                    HF_MODELS,
                    params={"pipeline_tag": tag, "sort": "downloads", "limit": str(limit)},
                    headers=headers,
                )
            except httpx.RequestError:
                continue
            if response.status_code >= 400:
                continue
            try:
                raw = response.json()
            except ValueError:
                continue
            if not isinstance(raw, list):
                continue
            for item in raw:
                if not isinstance(item, dict):
                    continue
                mid = str(item.get("id") or item.get("modelId") or "")
                if not mid:
                    continue
                caps = capabilities_from_pipeline_tag(str(item.get("pipeline_tag") or tag))
                if not caps:
                    continue
                models.append({
                    "id": mid,
                    "label": mid,
                    "capabilities": caps,
                    "live": True,
                    "source": "huggingface",
                })
    finally:
        if own:
            await http.aclose()
    return models
