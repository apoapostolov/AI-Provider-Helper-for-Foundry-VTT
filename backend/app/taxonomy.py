"""Normalize live model rows into the library taxonomy."""

from __future__ import annotations

from typing import Any

from app.capabilities import IMAGE_EDIT, IMAGE_GEN, VISION, capabilities_from_architecture, has_capability

MILLION = 1_000_000


def per_million(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    # OpenRouter stores USD per token. Values >= 0.01 are already per 1M.
    if number > 0 and number < 0.01:
        return round(number * MILLION, 6)
    return round(number, 6)


def per_image(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return round(number, 6)


def taxonomy_from_openrouter(item: dict[str, Any]) -> dict[str, Any]:
    arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    caps = capabilities_from_architecture(arch)
    return {
        "provider": _provider_from_id(str(item.get("id") or "")),
        "model": str(item.get("id") or ""),
        "label": str(item.get("name") or item.get("id") or ""),
        "vision": has_capability(caps, VISION),
        "imageGen": has_capability(caps, IMAGE_GEN),
        "imageEdit": has_capability(caps, IMAGE_EDIT),
        "capabilities": caps,
        "costIn": per_million(pricing.get("prompt")),
        "costInCached": per_million(
            pricing.get("input_cache_read")
            or pricing.get("input_cache_hits")
            or pricing.get("cached")
        ),
        "costOut": per_million(pricing.get("completion")),
        "costImage": per_image(pricing.get("image")) if has_capability(caps, IMAGE_GEN) else None,
        "contextLength": item.get("context_length") or item.get("contextLength"),
        "source": "openrouter",
        "live": True,
    }


def taxonomy_from_static(provider_id: str, model: dict[str, Any]) -> dict[str, Any]:
    caps = list(model.get("capabilities") or [])
    cost = model.get("cost") if isinstance(model.get("cost"), dict) else {}
    return {
        "provider": provider_id,
        "model": model.get("id"),
        "label": model.get("label") or model.get("id"),
        "vision": has_capability(caps, VISION),
        "imageGen": has_capability(caps, IMAGE_GEN),
        "imageEdit": has_capability(caps, IMAGE_EDIT),
        "capabilities": caps,
        "costIn": per_million(cost.get("prompt") or cost.get("costIn")),
        "costInCached": per_million(cost.get("costInCached") or cost.get("cached")),
        "costOut": per_million(cost.get("completion") or cost.get("costOut")),
        "costImage": per_image(cost.get("image") or cost.get("costImage")),
        "contextLength": model.get("contextLength"),
        "source": "seed",
        "live": bool(model.get("live")),
        "recommended": bool(model.get("recommended")),
        "alpha": model.get("alpha"),
    }


def merge_taxonomy(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = {**base}
    for key in ("vision", "imageGen", "imageEdit"):
        out[key] = bool(base.get(key) or extra.get(key))
    caps = list(dict.fromkeys([*(base.get("capabilities") or []), *(extra.get("capabilities") or [])]))
    out["capabilities"] = caps
    for key in ("costIn", "costInCached", "costOut", "costImage", "contextLength"):
        if extra.get(key) is not None and base.get(key) is None:
            out[key] = extra[key]
    if extra.get("label") and extra.get("source") != "seed":
        out["label"] = base.get("label") or extra.get("label")
    if extra.get("live"):
        out["live"] = True
        out["source"] = extra.get("source") or out.get("source")
    return out


def _provider_from_id(model_id: str) -> str:
    if "/" not in model_id:
        return ""
    return model_id.split("/", 1)[0]
