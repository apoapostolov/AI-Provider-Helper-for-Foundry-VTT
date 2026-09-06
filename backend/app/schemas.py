from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProbeRequest(BaseModel):
    provider: str
    endpoint: str = ""
    model: str = ""
    api_key: str = Field(default="", repr=False)
    consumer_id: str = ""
    refresh: bool = False
    capability: str = ""
    debug: bool = False


class ChatRequest(BaseModel):
    provider: str = ""
    endpoint: str = ""
    model: str = ""
    api_key: str = Field(default="", repr=False)
    consumer_id: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


class VisionRequest(BaseModel):
    provider: str = ""
    endpoint: str = ""
    model: str = ""
    api_key: str = Field(default="", repr=False)
    consumer_id: str = ""
    prompt: str = ""
    image: str = ""
    images: list[str] = Field(default_factory=list)


class ImageRequest(BaseModel):
    provider: str = ""
    endpoint: str = ""
    model: str = ""
    api_key: str = Field(default="", repr=False)
    consumer_id: str = ""
    prompt: str = ""
    width: int = 1024
    height: int = 1024
    images: list[str] = Field(default_factory=list)
    access_token: str = Field(default="", repr=False)
    background: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)
    mask: str = ""


class VaultUpsert(BaseModel):
    id: str = ""
    providerId: str = ""
    model: str = ""
    models: list[str] = Field(default_factory=list)
    label: str = "Key"
    kind: str = "key"
    grants: list[str] = Field(default_factory=list)
    enabled: bool | None = None
    secret: str = Field(default="", repr=False)


class QueryRequest(BaseModel):
    consumerId: str
    capability: str = ""
    providers: list[dict[str, Any]] = Field(default_factory=list)
    refresh: bool = False
    evaluationSources: list[str] | None = None
