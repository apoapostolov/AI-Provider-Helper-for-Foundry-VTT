"""Live model lists: public catalogs plus each provider /models when a key exists."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from app.capabilities import CHAT, EMBEDDINGS, IMAGE_EDIT, IMAGE_GEN, VISION, capabilities_from_architecture
from app.catalog import DEFAULT_ENDPOINTS
from app.huggingface import fetch_huggingface_models
from app.oauth import OAUTH_PROVIDERS, read_session
from app.openrouter import fetch_openrouter_models
from app.scrape import fetch_models_dev, flatten_models_dev
from app.vault import first_secret

LOCAL_IDS = ("ollama", "lmstudio", "vllm", "llamacpp")
SKIP_RE = re.compile(r"(whisper|tts|transcri|moderation|davinci|babbage|ada-00|realtime|audio)", re.I)
IMAGE_RE = re.compile(r"(gpt-image|dall-e|imagen|flux|imagine|stable-diffusion|image-gen)", re.I)
VISION_RE = re.compile(r"(vl\b|vision|pixtral|llava|gpt-4o|gpt-4\.1|gpt-5|claude|gemini|grok|glm-4)", re.I)
EMBED_RE = re.compile(r"embed", re.I)


def infer_capabilities(model_id: str, provider_caps: list[str] | None = None) -> list[str]:
    mid = str(model_id or "")
    if EMBED_RE.search(mid):
        return [EMBEDDINGS]
    if SKIP_RE.search(mid):
        return []
    if IMAGE_RE.search(mid):
        caps = [IMAGE_GEN]
        if re.search(r"(gpt-image|imagen|flux|imagine|edit)", mid, re.I):
            caps.append(IMAGE_EDIT)
        return caps
    caps = [CHAT]
    if VISION_RE.search(mid) or VISION in (provider_caps or []):
        caps.append(VISION)
    return caps


def merge_model_lists(seed: list[dict[str, Any]], live: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in seed or []:
        mid = str(row.get("id") or "")
        if mid:
            by_id[mid] = dict(row)
    for row in live or []:
        mid = str(row.get("id") or "")
        if not mid:
            continue
        prev = by_id.get(mid)
        if prev:
            next_row = {**row, **prev}
            if row.get("cost") and not prev.get("cost"):
                next_row["cost"] = row["cost"]
            if row.get("capabilities") and not prev.get("capabilities"):
                next_row["capabilities"] = row["capabilities"]
            next_row["live"] = True
            by_id[mid] = next_row
        else:
            by_id[mid] = dict(row)
    return list(by_id.values())


def _normalize_openai_models(raw: object, provider_id: str, provider_caps: list[str] | None = None) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        items = raw.get("data") or raw.get("models") or raw.get("items") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            mid = item
            label = item
            caps: list[str] = []
            context = None
        elif isinstance(item, dict):
            mid = str(item.get("id") or item.get("name") or "")
            if mid.startswith("models/"):
                mid = mid.split("/", 1)[1]
            label = str(item.get("displayName") or item.get("display_name") or item.get("name") or mid)
            arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else None
            caps = capabilities_from_architecture(arch) if arch else []
            context = item.get("context_length") or item.get("inputTokenLimit")
        else:
            continue
        if not mid:
            continue
        if not caps:
            caps = infer_capabilities(mid, provider_caps)
        if not caps:
            continue
        out.append({
            "id": mid,
            "label": label,
            "capabilities": caps,
            "contextLength": context,
            "live": True,
            "source": provider_id,
        })
    return out


def _headers(provider_id: str, token: str) -> dict[str, str]:
    if not token:
        return {"Accept": "application/json"}
    if provider_id == "anthropic":
        return {"Accept": "application/json", "x-api-key": token, "anthropic-version": "2023-06-01"}
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    if provider_id == "openai-codex":
        headers["User-Agent"] = "codex-cli"
    return headers


def _models_url(provider_id: str, endpoint: str, token: str) -> str:
    base = endpoint.rstrip("/")
    if provider_id == "gemini" and "generativelanguage.googleapis.com" in base:
        native = "https://generativelanguage.googleapis.com/v1beta"
        if token:
            return f"{native}/models?key={token}"
        return f"{native}/openai/models"
    if provider_id == "ollama":
        return "http://127.0.0.1:11434/api/tags"
    return f"{base}/models"


async def fetch_provider_models(
    provider_id: str,
    *,
    token: str = "",
    endpoint: str = "",
    provider_caps: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    if provider_id == "openai-codex":
        return []
    url = _models_url(provider_id, endpoint or DEFAULT_ENDPOINTS.get(provider_id, ""), token)
    if not url:
        return []
    own = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    try:
        response = await http.get(url, headers=_headers(provider_id, token))
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
    if provider_id == "ollama" and isinstance(payload, dict) and isinstance(payload.get("models"), list):
        names = []
        for item in payload["models"]:
            if isinstance(item, dict):
                names.append({"id": item.get("name") or item.get("model"), "name": item.get("name")})
        return _normalize_openai_models(names, provider_id, provider_caps)
    return _normalize_openai_models(payload, provider_id, provider_caps)


async def refresh_all(cfg) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    async with httpx.AsyncClient(timeout=20.0) as http:
        dev, openrouter, huggingface = await asyncio.gather(
            fetch_models_dev(client=http),
            fetch_openrouter_models(getattr(cfg, "openrouter_key", ""), client=http),
            fetch_huggingface_models(getattr(cfg, "hf_token", ""), client=http),
            return_exceptions=True,
        )
        out: dict[str, list[dict[str, Any]]] = {}
        if isinstance(dev, dict):
            out.update(dev)
        extras = flatten_models_dev(out) if isinstance(dev, dict) else []
        if isinstance(openrouter, list) and openrouter:
            out["openrouter"] = merge_model_lists(out.get("openrouter") or [], openrouter)
        if isinstance(huggingface, list) and huggingface:
            out["huggingface"] = merge_model_lists(out.get("huggingface") or [], huggingface)

        jobs: list[tuple[str, Any]] = []
        cache = getattr(cfg, "cache_dir", None)
        for pid, endpoint in DEFAULT_ENDPOINTS.items():
            if pid in {"openrouter", "huggingface", "openai-codex"}:
                continue
            token = ""
            if cache is not None:
                if pid in OAUTH_PROVIDERS:
                    session = read_session(cache, pid)
                    token = str((session or {}).get("access_token") or "")
                else:
                    token = first_secret(cache, pid)
            if not token and pid not in LOCAL_IDS:
                continue
            jobs.append((pid, fetch_provider_models(pid, token=token, endpoint=endpoint, client=http)))
        if jobs:
            fetched = await asyncio.gather(*(job for _, job in jobs), return_exceptions=True)
            for (pid, _), result in zip(jobs, fetched, strict=False):
                if isinstance(result, list) and result:
                    out[pid] = merge_model_lists(out.get(pid) or [], result)
                    if pid == "openai":
                        out["openai-codex"] = merge_model_lists(out.get("openai-codex") or [], result)
                    if pid == "xai":
                        out["xai-oauth"] = merge_model_lists(out.get("xai-oauth") or [], result)
    return out, extras
