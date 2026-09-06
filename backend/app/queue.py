"""Per-provider request queue. OAuth/Codex is 1-wide. Key APIs allow 2."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.oauth import OAUTH_PROVIDERS

T = TypeVar("T")


class ProviderQueue:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Semaphore] = {}

    def _sema(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._locks:
            width = 1 if provider in OAUTH_PROVIDERS else 2
            self._locks[provider] = asyncio.Semaphore(width)
        return self._locks[provider]

    async def run(self, provider: str, job: Callable[[], Awaitable[T]]) -> T:
        async with self._sema(provider or "unknown"):
            return await job()
