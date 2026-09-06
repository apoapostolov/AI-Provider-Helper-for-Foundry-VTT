from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.catalog import filter_catalog, seed_catalog
from app.chat import chat_completions
from app.config import Config
from app.fetch_image import fetch_image
from app.evaluations import SOURCE_IDS, enrich_catalog_rows, enrich_query_models, public_payload, refresh_source
from app.images import generate_image
from app.live_models import merge_model_lists, refresh_all
from app.oauth import disconnect as oauth_disconnect
from app.oauth import poll_flow, read_session, session_status, start_flow
from app.probe import probe_provider
from app.query import build_query
from app.queue import ProviderQueue
from app.quota import get_quota, poll_all
from app.schemas import ChatRequest, ImageRequest, ProbeRequest, QueryRequest, VaultUpsert, VisionRequest
from app.vault import VaultError, delete_credential, find_granted, list_credentials, resolve_secret, upsert_credential
from app.vision import vision_complete

# Foundry is often opened by LAN IP or hostname on the same machine.
LOCAL_ORIGIN_RE = (
    r"https?://("
    r"localhost|127\.0\.0\.1|\[::1\]|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
    r"100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}|"
    r"[A-Za-z0-9-]+|"
    r"[A-Za-z0-9-]+\.local"
    r")(:\d+)?"
)


def origin_pattern_to_regex(pattern: str) -> str:
    raw = pattern.strip()
    if not raw or raw == "*":
        raise ValueError("refusing wildcard CORS origin")
    if "\\" in raw:
        return raw
    if "://" not in raw:
        raw = f"https://{raw}"
    escaped = re.escape(raw).replace(r"\*", r"[A-Za-z0-9.-]+")
    hostport = raw.split("://", 1)[-1]
    if not re.search(r":\d+$", hostport):
        escaped += r"(:\d+)?"
    return escaped


def cors_origin_regex(extra: str = "") -> str:
    clauses = [f"(?:{LOCAL_ORIGIN_RE})"]
    for item in extra.split(","):
        item = item.strip()
        if not item:
            continue
        clauses.append(f"(?:{origin_pattern_to_regex(item)})")
    return "|".join(clauses)


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config.from_env()
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="AI Provider Library", version="14.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=cors_origin_regex(cfg.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_private_network=True,
    )
    app.state.config = cfg
    app.state.queue = ProviderQueue()
    app.state.live_openrouter: list[dict[str, Any]] = []
    app.state.live_huggingface: list[dict[str, Any]] = []
    app.state.live_extras: list[dict[str, Any]] = []
    app.state.live_by_provider: dict[str, list[dict[str, Any]]] = {}

    def _inject(provider: str, consumer_id: str, api_key: str) -> str:
        token = resolve_secret(cfg.cache_dir, provider, consumer_id, api_key)
        if token:
            return token
        if consumer_id and not api_key:
            row = find_granted(cfg.cache_dir, provider, consumer_id)
            if not row:
                raise HTTPException(status_code=401, detail="No key shared with this module")
            if (row.get("kind") or "") == "oauth":
                raise HTTPException(status_code=401, detail="Connect this provider in AI Keys")
            raise HTTPException(status_code=401, detail="No key stored for this provider")
        return api_key

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "ai-provider-library",
            "port": cfg.port,
            "debug": cfg.debug,
            "vault": len(list_credentials(cfg.cache_dir)),
        }

    def _source_set(value: Any) -> set[str] | None:
        if value is None:
            return None
        values = value if isinstance(value, list) else str(value).split(",")
        return {str(item).strip() for item in values if str(item).strip() in SOURCE_IDS}

    async def _refresh_live() -> None:
        live, extras = await refresh_all(cfg)
        app.state.live_by_provider = live
        app.state.live_openrouter = live.get("openrouter") or []
        app.state.live_huggingface = live.get("huggingface") or []
        app.state.live_extras = extras

    @app.get("/v1/catalog")
    async def catalog(capability: str = "", refresh: int = 0, source: str = "", sources: str | None = None) -> dict[str, Any]:
        if refresh:
            await _refresh_live()
        rows = seed_catalog()
        for row in rows:
            live = app.state.live_by_provider.get(row["id"]) or []
            if live:
                row["models"] = merge_model_lists(row.get("models") or [], live)
        filtered = enrich_catalog_rows(filter_catalog(rows, capability), cfg.cache_dir, _source_set(sources if sources is not None else source))
        return {
            "ok": True,
            "capability": capability or None,
            "providers": filtered,
            "openrouter": len(app.state.live_openrouter),
            "huggingface": len(app.state.live_huggingface),
            "live": {key: len(val) for key, val in app.state.live_by_provider.items()},
        }

    @app.post("/v1/query")
    async def query_route(body: QueryRequest) -> dict[str, Any]:
        if body.refresh:
            await _refresh_live()
        return build_query(
            consumer_id=body.consumerId,
            capability=body.capability,
            providers=body.providers or None,
            seed=seed_catalog(),
            openrouter=app.state.live_openrouter,
            huggingface=app.state.live_huggingface,
            extras=app.state.live_extras,
            live_by_provider=app.state.live_by_provider,
            cache_dir=cfg.cache_dir,
            evaluation_sources=_source_set(body.evaluationSources),
        )

    @app.get("/v1/evaluations")
    def evaluations_list(sources: str | None = None) -> dict[str, Any]:
        return public_payload(cfg.cache_dir, _source_set(sources))

    @app.post("/v1/evaluations/refresh")
    async def evaluations_refresh(body: dict[str, Any]) -> dict[str, Any]:
        source_id = str(body.get("source") or "")
        try:
            return await refresh_source(
                cfg.cache_dir,
                source_id,
                _source_set(body.get("sources")),
                api_key=str(body.get("apiKey") or "")
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/vault")
    def vault_list() -> dict[str, Any]:
        return {"ok": True, "credentials": list_credentials(cfg.cache_dir)}

    @app.post("/v1/vault")
    def vault_put(body: VaultUpsert) -> dict[str, Any]:
        try:
            row = upsert_credential(
                cfg.cache_dir,
                cred_id=body.id,
                provider_id=body.providerId,
                label=body.label,
                kind=body.kind,
                grants=body.grants,
                enabled=body.enabled,
                secret=body.secret,
                model=body.model,
                models=body.models,
            )
        except VaultError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "credential": row}

    @app.delete("/v1/vault/{cred_id}")
    def vault_delete(cred_id: str) -> dict[str, Any]:
        if not delete_credential(cfg.cache_dir, cred_id):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}

    @app.post("/v1/providers/probe")
    async def providers_probe(body: ProbeRequest) -> dict[str, Any]:
        body.api_key = _inject(body.provider, body.consumer_id or "", body.api_key or "")
        return await probe_provider(body, cache_dir=cfg.cache_dir)

    @app.get("/v1/providers/{provider_id}/oauth/status")
    def oauth_status(provider_id: str) -> dict[str, Any]:
        try:
            return session_status(cfg.cache_dir, provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/providers/{provider_id}/oauth/start")
    async def oauth_start(provider_id: str) -> dict[str, Any]:
        try:
            return await start_flow(provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/providers/{provider_id}/oauth/poll")
    async def oauth_poll(provider_id: str, body: dict[str, Any]) -> dict[str, Any]:
        flow_id = str(body.get("flow_id") or "")
        if not flow_id:
            raise HTTPException(status_code=400, detail="flow_id is required")
        try:
            return await poll_flow(provider_id, flow_id, cfg.cache_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/providers/{provider_id}/oauth/token")
    def oauth_token(provider_id: str) -> dict[str, Any]:
        row = read_session(cfg.cache_dir, provider_id)
        if not row:
            raise HTTPException(status_code=404, detail="not connected")
        return {"access_token": row.get("access_token") or "", "expires_at": row.get("expires_at")}

    @app.delete("/v1/providers/{provider_id}/oauth")
    def oauth_delete(provider_id: str) -> dict[str, Any]:
        try:
            oauth_disconnect(cfg.cache_dir, provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/v1/chat/completions")
    async def chat_route(body: ChatRequest) -> dict[str, Any]:
        body.api_key = _inject(body.provider, body.consumer_id, body.api_key)
        return await app.state.queue.run(body.provider, lambda: chat_completions(body))

    @app.post("/v1/vision/complete")
    async def vision_route(body: VisionRequest) -> dict[str, Any]:
        body.api_key = _inject(body.provider, body.consumer_id, body.api_key)
        return await app.state.queue.run(body.provider, lambda: vision_complete(body))

    @app.post("/v1/images/generations")
    async def images_generate(body: ImageRequest) -> dict[str, Any]:
        body.api_key = _inject(body.provider, body.consumer_id, body.api_key)
        return await app.state.queue.run(body.provider, lambda: generate_image(body, cfg.cache_dir))

    @app.post("/v1/images/edits")
    async def images_edit(body: ImageRequest) -> dict[str, Any]:
        body.api_key = _inject(body.provider, body.consumer_id, body.api_key)
        return await app.state.queue.run(body.provider, lambda: generate_image(body, cfg.cache_dir))

    @app.post("/v1/codex/images")
    async def codex_images(body: ImageRequest) -> dict[str, Any]:
        body.provider = "openai-codex"
        body.api_key = _inject(body.provider, body.consumer_id, body.api_key)
        return await app.state.queue.run(body.provider, lambda: generate_image(body, cfg.cache_dir))

    @app.get("/v1/quota")
    def quota_get(provider: str = "") -> dict[str, Any]:
        return {"ok": True, "quota": get_quota(cfg.cache_dir, provider)}

    @app.post("/v1/quota/poll")
    async def quota_poll() -> dict[str, Any]:
        return {"ok": True, "quota": await poll_all(cfg.cache_dir)}

    @app.post("/v1/fetch-image")
    def fetch_image_route(body: dict[str, Any]):
        return fetch_image(str(body.get("url") or ""))

    @app.post("/v1/shutdown")
    def shutdown() -> dict[str, Any]:
        def die() -> None:
            time.sleep(0.2)
            os._exit(0)

        threading.Thread(target=die, daemon=True).start()
        return {"ok": True}

    return app


app = create_app()
