from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.catalog import DEFAULT_ENDPOINTS
from app.oauth import generate_codex_chat, short_provider_error
from app.schemas import ChatRequest


def _headers(provider: str, api_key: str) -> dict[str, str]:
    if not api_key:
        return {"Content-Type": "application/json"}
    if provider == "anthropic":
        return {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/apoapostolov/AI-Provider-Library-for-Foundry-VTT"
        headers["X-Title"] = "AI Provider Library"
    return headers


def _raise_provider(response: httpx.Response) -> None:
    host = ""
    try:
        host = response.request.url.host or ""
    except Exception:
        host = ""
    raise HTTPException(
        status_code=502,
        detail=short_provider_error(response.status_code, response.text, host),
    )


async def chat_completions(req: ChatRequest) -> dict[str, Any]:
    if req.provider == "openai-codex":
        if not req.api_key:
            raise HTTPException(status_code=401, detail="Connect this provider in AI Keys")
        if not req.messages:
            raise HTTPException(status_code=400, detail="messages is required")
        try:
            text = await generate_codex_chat(req.api_key, req.messages, req.model, req.extras)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"choices": [{"message": {"role": "assistant", "content": text}}]}

    endpoint = (req.endpoint or DEFAULT_ENDPOINTS.get(req.provider, "")).rstrip("/")
    if not endpoint:
        raise HTTPException(status_code=400, detail="No endpoint")
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages is required")
    payload = {"model": req.model, "messages": req.messages, **req.extras}
    async with httpx.AsyncClient(timeout=180.0) as http:
        try:
            response = await http.post(
                f"{endpoint}/chat/completions",
                headers=_headers(req.provider, req.api_key),
                json=payload,
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if response.status_code >= 400:
        _raise_provider(response)
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Provider returned no JSON") from exc
