"""Build the consumer query payload: catalog + taxonomy + grant flag."""

from __future__ import annotations

from typing import Any

from app.capabilities import has_capability
from app.evaluations import enrich_query_models
from app.catalog import DEFAULT_ENDPOINTS, seed_catalog
from app.taxonomy import merge_taxonomy, taxonomy_from_openrouter, taxonomy_from_static
from app.vault import find_granted
from app.quota import get_quota


def build_query(
    *,
    consumer_id: str,
    capability: str = "",
    providers: list[dict[str, Any]] | None = None,
    seed: list[dict[str, Any]] | None = None,
    openrouter: list[dict[str, Any]] | None = None,
    huggingface: list[dict[str, Any]] | None = None,
    extras: list[dict[str, Any]] | None = None,
    live_by_provider: dict[str, list[dict[str, Any]]] | None = None,
    cache_dir,
    evaluation_sources: set[str] | None = None,
) -> dict[str, Any]:
    allow = _allowlist(providers)
    or_by_id = {str(item.get("id")): item for item in (openrouter or []) if item.get("id")}
    extra_by_id = {str(item.get("id")): item for item in (extras or []) if item.get("id")}
    live_map = live_by_provider or {}
    out: list[dict[str, Any]] = []
    for row in seed or seed_catalog():
        pid = row["id"]
        if allow is not None and pid not in allow:
            continue
        models = [taxonomy_from_static(pid, model) for model in row.get("models") or []]
        live_rows = list(live_map.get(pid) or [])
        if pid == "openrouter" and openrouter:
            live_rows = list(openrouter)
            models = _merge_live(models, [taxonomy_from_openrouter(item) for item in live_rows], pid)
        else:
            if pid == "huggingface" and huggingface:
                live_rows = live_rows or list(huggingface)
            if live_rows:
                models = _merge_live(models, [taxonomy_from_static(pid, item) for item in live_rows], pid)
        models = [_fill_from_openrouter(model, or_by_id, extra_by_id) for model in models]
        models = enrich_query_models(models, cache_dir, evaluation_sources)
        if allow and allow.get(pid):
            wanted = allow[pid]
            models = [model for model in models if model["model"] in wanted]
        if capability:
            models = [model for model in models if has_capability(model.get("capabilities"), capability)]
            if not models and not has_capability(row.get("capabilities"), capability):
                continue
        granted_row = find_granted(cache_dir, pid, consumer_id) if consumer_id else None
        out.append({
            "id": pid,
            "name": row.get("name") or pid,
            "kind": row.get("kind"),
            "auth": row.get("auth"),
            "defaultEndpoint": row.get("defaultEndpoint") or DEFAULT_ENDPOINTS.get(pid, ""),
            "capabilities": row.get("capabilities") or [],
            "granted": bool(granted_row),
            "credentialId": (granted_row or {}).get("id"),
            "quota": get_quota(cache_dir, pid) if cache_dir else None,
            "models": models,
        })
    return {"ok": True, "consumerId": consumer_id, "capability": capability or None, "providers": out}


def _allowlist(providers: list[dict[str, Any]] | None) -> dict[str, set[str]] | None:
    if not providers:
        return None
    allow: dict[str, set[str]] = {}
    for item in providers:
        pid = str(item.get("id") or item.get("providerId") or "")
        if not pid:
            continue
        models = item.get("models") or []
        allow[pid] = {str(mid) for mid in models if mid}
    return allow


def _merge_live(seed: list[dict[str, Any]], live: list[dict[str, Any]], provider_id: str) -> list[dict[str, Any]]:
    by_id = {row["model"]: row for row in seed}
    for row in live:
        mid = row.get("model")
        if not mid:
            continue
        row["provider"] = provider_id
        if mid in by_id:
            by_id[mid] = merge_taxonomy(by_id[mid], row)
        else:
            by_id[mid] = row
    return list(by_id.values())


def _fill_from_openrouter(
    model: dict[str, Any],
    or_by_id: dict[str, dict[str, Any]],
    extra_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    mid = str(model.get("model") or "")
    aliases = [mid]
    if "/" not in mid and model.get("provider"):
        aliases.append(f"{_or_slug(model['provider'])}/{mid}")
    hit = None
    for alias in aliases:
        if alias in or_by_id:
            hit = taxonomy_from_openrouter(or_by_id[alias])
            break
    if hit:
        model = merge_taxonomy(model, hit)
    extra = extra_by_id.get(mid) or extra_by_id.get(aliases[-1] if aliases else "")
    if extra:
        for key in ("costIn", "costInCached", "costOut", "costImage"):
            if model.get(key) is None and extra.get(key) is not None:
                model[key] = extra[key]
    return model


def _or_slug(provider_id: str) -> str:
    return {
        "openai": "openai",
        "anthropic": "anthropic",
        "gemini": "google",
        "xai": "x-ai",
        "xai-oauth": "x-ai",
        "mistral": "mistralai",
        "deepseek": "deepseek",
        "qwen": "qwen",
    }.get(provider_id, provider_id)
