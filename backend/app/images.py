from __future__ import annotations

import base64
import re
from typing import Any

import httpx
from fastapi import HTTPException

from app.catalog import DEFAULT_ENDPOINTS
from app.oauth import generate_codex_image, read_session
from app.schemas import ImageRequest

MASK_MAX_BYTES = 4 * 1024 * 1024
_DATA_URL = re.compile(r"^data:([^;,]+);base64,(.+)$", re.DOTALL)
_SNAP_MODELS = ("dall-e-2", "dall-e-3")
_GROK_PROVIDERS = {"xai", "xai-oauth"}
_ASPECTS = (
    (1, 1, "1:1"),
    (16, 9, "16:9"),
    (9, 16, "9:16"),
    (4, 3, "4:3"),
    (3, 4, "3:4"),
    (3, 2, "3:2"),
    (2, 3, "2:3"),
    (2, 1, "2:1"),
    (1, 2, "1:2"),
)


def _size(width: int, height: int) -> str:
    """Legacy 1024/1536 snap for hosts that still require those buckets."""
    ratio = (width or 1) / (height or 1)
    if ratio > 1.15:
        return "1536x1024"
    if ratio < 0.87:
        return "1024x1536"
    return "1024x1024"


def _needs_legacy_snap(model: str) -> bool:
    ident = (model or "").lower()
    if any(token in ident for token in _SNAP_MODELS):
        return True
    if "gpt-image-1.5" in ident or "gpt-image-2" in ident:
        return False
    return "gpt-image-1" in ident


def _align16(value: int) -> int:
    return max(16, (int(value) // 16) * 16)


def _native_size(width: int, height: int) -> str:
    """GPT Image 2 native size: max edge 3840, multiples of 16, ratio <= 3:1."""
    w = _align16(width or 1024)
    h = _align16(height or 1024)
    longest = max(w, h)
    if longest > 3840:
        scale = 3840 / longest
        w = _align16(int(w * scale))
        h = _align16(int(h * scale))
    if w > h * 3:
        w = _align16(h * 3)
    if h > w * 3:
        h = _align16(w * 3)
    pixels = w * h
    if pixels > 8_294_400:
        scale = (8_294_400 / pixels) ** 0.5
        w = _align16(int(w * scale))
        h = _align16(int(h * scale))
    return f"{w}x{h}"


def image_size(model: str, width: int, height: int) -> str:
    if _needs_legacy_snap(model):
        return _size(width, height)
    return _native_size(width, height)


def resolve_mask(req: ImageRequest) -> str:
    raw = req.mask or (req.extras or {}).get("mask") or ""
    return str(raw).strip()


def decode_data_url(url: str) -> tuple[str, bytes]:
    match = _DATA_URL.match(str(url or "").strip())
    if not match:
        raise HTTPException(status_code=400, detail="Image must be a PNG data URL")
    try:
        data = base64.b64decode(match.group(2), validate=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid image data") from exc
    return match.group(1), data


def mask_bytes(req: ImageRequest) -> bytes | None:
    raw = resolve_mask(req)
    if not raw:
        return None
    _mime, data = decode_data_url(raw)
    if len(data) > MASK_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Mask PNG must be under 4 MB")
    return data


def grok_edit_body(req: ImageRequest) -> dict[str, Any]:
    urls = [str(item) for item in (req.images or []) if item][:3]
    body: dict[str, Any] = {
        "model": req.model,
        "prompt": req.prompt,
        "response_format": "b64_json",
    }
    refs = [{"type": "image_url", "url": url} for url in urls]
    if len(refs) == 1:
        body["image"] = refs[0]
    elif refs:
        body["images"] = refs
    ratio = (req.width or 1) / (req.height or 1)
    body["aspect_ratio"] = min(_ASPECTS, key=lambda item: abs(ratio - item[0] / item[1]))[2]
    return body


def openai_edit_form(req: ImageRequest) -> tuple[dict[str, str], list[tuple[str, tuple[str, bytes, str]]]]:
    form = {
        "model": req.model or "",
        "prompt": req.prompt,
        "size": image_size(req.model or "", req.width, req.height),
    }
    if req.background:
        form["background"] = req.background
        if req.background == "transparent":
            form["output_format"] = "png"
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for index, url in enumerate(req.images or []):
        mime, data = decode_data_url(str(url))
        files.append(("image[]", (f"image{index}.png", data, mime or "image/png")))
    mask = mask_bytes(req)
    if mask:
        files.append(("mask", ("mask.png", mask, "image/png")))
    return form, files


async def generate_image(req: ImageRequest, cache_dir) -> dict[str, Any]:
    if req.provider == "openai-codex":
        token = req.access_token or req.api_key
        if not token:
            row = read_session(cache_dir, "openai-codex") or {}
            token = str(row.get("access_token") or "")
        if not token:
            raise HTTPException(status_code=401, detail="Codex is not connected.")
        if not req.prompt:
            raise HTTPException(status_code=400, detail="prompt is required")
        try:
            b64 = await generate_codex_image(
                token,
                req.prompt,
                req.width,
                req.height,
                req.model or "gpt-image-2",
                req.images,
                req.background,
                image_size(req.model or "gpt-image-2", req.width, req.height),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"b64": b64}

    endpoint = (req.endpoint or DEFAULT_ENDPOINTS.get(req.provider, "")).rstrip("/")
    if not endpoint:
        raise HTTPException(status_code=400, detail="No endpoint")
    if not req.prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    if req.provider == "gemini":
        return await _gemini_image(endpoint, req)
    headers = {"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"}
    if req.provider == "openrouter":
        return await _openrouter_image(endpoint, req, headers)
    if req.provider in _GROK_PROVIDERS:
        return await _grok_image(endpoint, req, headers)
    if req.images:
        return await _openai_edit(endpoint, req)
    return await _openai_generate(endpoint, req, headers)


async def _openai_generate(endpoint: str, req: ImageRequest, headers: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": req.model,
        "prompt": req.prompt,
        "size": image_size(req.model or "", req.width, req.height),
    }
    if req.background:
        payload["background"] = req.background
        if req.background == "transparent":
            payload["output_format"] = "png"
    async with httpx.AsyncClient(timeout=180.0) as http:
        try:
            response = await http.post(f"{endpoint}/images/generations", headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:400])
    return response.json()


async def _openai_edit(endpoint: str, req: ImageRequest) -> dict[str, Any]:
    form, files = openai_edit_form(req)
    async with httpx.AsyncClient(timeout=180.0) as http:
        try:
            response = await http.post(
                f"{endpoint}/images/edits",
                headers={"Authorization": f"Bearer {req.api_key}"},
                data=form,
                files=files,
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:400])
    return response.json()


async def _grok_image(endpoint: str, req: ImageRequest, headers: dict[str, str]) -> dict[str, Any]:
    if req.images:
        payload = grok_edit_body(req)
        path = "/images/edits"
    else:
        ratio = (req.width or 1) / (req.height or 1)
        payload = {
            "model": req.model,
            "prompt": req.prompt,
            "n": 1,
            "aspect_ratio": min(_ASPECTS, key=lambda item: abs(ratio - item[0] / item[1]))[2],
            "resolution": "2K" if max(req.width or 0, req.height or 0) >= 1536 else "1K",
            "response_format": "b64_json",
        }
        path = "/images/generations"
    async with httpx.AsyncClient(timeout=180.0) as http:
        try:
            response = await http.post(f"{endpoint}{path}", headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:400])
    return response.json()


async def _gemini_image(endpoint: str, req: ImageRequest) -> dict[str, Any]:
    url = f"{endpoint}/models/{req.model}:generateContent"
    if req.api_key:
        url += f"?key={req.api_key}"
    parts: list[dict[str, Any]] = [{"text": req.prompt}]
    for item in req.images or []:
        mime, data = decode_data_url(str(item))
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    async with httpx.AsyncClient(timeout=180.0) as http:
        response = await http.post(url, json=payload)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:400])
    return response.json()


async def _openrouter_image(endpoint: str, req: ImageRequest, headers: dict[str, str]) -> dict[str, Any]:
    payload = {
        "model": req.model,
        "messages": [{"role": "user", "content": req.prompt}],
        "modalities": ["image", "text"],
    }
    headers = {
        **headers,
        "HTTP-Referer": "https://github.com/apoapostolov/AI-Provider-Library-for-Foundry-VTT",
        "X-Title": "AI Provider Library",
    }
    async with httpx.AsyncClient(timeout=180.0) as http:
        response = await http.post(f"{endpoint}/chat/completions", headers=headers, json=payload)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:400])
    return response.json()
