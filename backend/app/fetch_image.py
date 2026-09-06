from __future__ import annotations

from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from fastapi.responses import Response


def fetch_image(url: str) -> Response:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise HTTPException(status_code=400, detail="https url required")
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="blocked host")
    try:
        upstream = httpx.get(url, timeout=30.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if upstream.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"upstream {upstream.status_code}")
    ctype = (upstream.headers.get("content-type") or "image/png").split(";", 1)[0]
    if not ctype.startswith("image/"):
        raise HTTPException(status_code=502, detail=f"not an image: {ctype}")
    return Response(content=upstream.content, media_type=ctype)
