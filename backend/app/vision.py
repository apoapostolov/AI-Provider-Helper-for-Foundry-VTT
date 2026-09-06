from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.chat import chat_completions
from app.schemas import ChatRequest, VisionRequest


def _content(prompt: str, images: list[str]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image in images:
        if not image:
            continue
        parts.append({"type": "image_url", "image_url": {"url": image}})
    return parts


async def vision_complete(req: VisionRequest) -> dict[str, Any]:
    images = list(req.images or [])
    if req.image:
        images.insert(0, req.image)
    if not req.prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    if not images:
        raise HTTPException(status_code=400, detail="image is required")
    chat = ChatRequest(
        provider=req.provider,
        endpoint=req.endpoint,
        model=req.model,
        api_key=req.api_key,
        messages=[{"role": "user", "content": _content(req.prompt, images)}],
    )
    return await chat_completions(chat)
