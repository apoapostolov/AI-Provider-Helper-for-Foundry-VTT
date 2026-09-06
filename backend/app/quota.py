"""Quota snapshots. Adapters cover hosts that expose remaining credit or quota."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.oauth import OAUTH_PROVIDERS, chatgpt_account_id, ensure_fresh_session, read_session
from app.vault import list_credentials, resolve_secret

SNAPSHOT = "quota.json"


def load_snapshots(cache_dir: str | Path) -> dict[str, Any]:
    path = Path(cache_dir) / SNAPSHOT
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_snapshots(cache_dir: str | Path, data: dict[str, Any]) -> None:
    path = Path(cache_dir) / SNAPSHOT
    path.write_text(json.dumps(data), encoding="utf-8")


def get_quota(cache_dir: str | Path, provider_id: str = "") -> dict[str, Any]:
    data = load_snapshots(cache_dir)
    if provider_id:
        return public_quota(data.get(provider_id)) or {"provider": provider_id, "ok": False, "reason": "no-data"}
    return {key: public_quota(value) for key, value in data.items() if isinstance(value, dict)}


def _now() -> int:
    return int(time.time())


def _metric(name: str, category: str, *, kind: str, amount: float | None = None, used: float | None = None, limit: float | None = None, unit: str = "", period: str = "", resets_at: str | None = None) -> dict[str, Any]:
    value: dict[str, Any]
    if kind == "bounded":
        value = {"kind": "bounded", "used": used, "limit": limit, "unit": unit}
    elif kind == "unbounded":
        value = {"kind": "unbounded", "amount": amount, "unit": unit}
    else:
        value = {"kind": "unavailable"}
    row = {"name": name, "category": category, "value": value, "period": {"kind": "rolling", "label": period or category}}
    if resets_at:
        row["resetsAt"] = resets_at
    return row


def public_quota(snap: dict[str, Any] | None) -> dict[str, Any] | None:
    if not snap:
        return None
    remaining = None
    resets = snap.get("resetsAt")
    for metric in snap.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        if not resets and metric.get("resetsAt"):
            resets = metric["resetsAt"]
        value = metric.get("value") or {}
        if remaining is not None:
            continue
        if value.get("kind") == "unbounded" and value.get("amount") is not None:
            remaining = {"amount": value.get("amount"), "unit": value.get("unit") or ""}
        elif value.get("kind") == "bounded" and value.get("limit") is not None:
            used = float(value.get("used") or 0)
            limit = float(value.get("limit") or 0)
            remaining = {"amount": max(0.0, limit - used), "used": used, "limit": limit, "unit": value.get("unit") or ""}
    return {
        "provider": snap.get("provider"),
        "ok": bool(snap.get("ok")),
        "polledAt": snap.get("polledAt"),
        "remaining": remaining,
        "resetsAt": resets,
        "metrics": snap.get("metrics") or [],
        "reason": snap.get("reason"),
    }


async def poll_all(cache_dir: str | Path) -> dict[str, Any]:
    data = load_snapshots(cache_dir)
    seen: set[str] = set()
    jobs: list[tuple[str, str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0) as http:
        for row in list_credentials(cache_dir):
            pid = str(row.get("providerId") or "")
            if not pid:
                continue
            seen.add(pid)
            grant = (row.get("grants") or [""])[0]
            token = resolve_secret(cache_dir, pid, grant)
            oauth_host = "xai-oauth" if pid == "xai" else pid
            if oauth_host in OAUTH_PROVIDERS:
                sess = await ensure_fresh_session(http, cache_dir, oauth_host)
                if not token:
                    token = str(sess.get("access_token") or "")
            if not token and pid not in {"ollama", "vllm", "lmstudio", "llamacpp"}:
                data[pid] = {"provider": pid, "ok": False, "reason": "no-key", "polledAt": _now()}
                continue
            jobs.append((pid, token, row.get("id")))
        for pid in OAUTH_PROVIDERS:
            if pid in seen:
                continue
            sess = await ensure_fresh_session(http, cache_dir, pid)
            token = str(sess.get("access_token") or "")
            if not token:
                continue
            jobs.append((pid, token, None))
        snaps = await asyncio.gather(*[
            _poll_one(http, pid, token, cred, data.get(pid)) for pid, token, cred in jobs
        ])
        for (pid, _token, _cred), snap in zip(jobs, snaps):
            data[pid] = snap
    save_snapshots(cache_dir, data)
    return data


async def _poll_one(http: httpx.AsyncClient, pid: str, token: str, credential_id: Any, prev: dict[str, Any] | None) -> dict[str, Any]:
    try:
        host = "xai-oauth" if pid == "xai" else pid
        snap = await poll_provider(http, host, token)
    except Exception:
        return {**(prev or {}), "provider": pid, "ok": False, "reason": "poll-failed", "polledAt": _now()}
    snap["provider"] = pid
    snap["polledAt"] = _now()
    if credential_id:
        snap["credentialId"] = credential_id
    return snap


async def poll_provider(http: httpx.AsyncClient, provider: str, token: str) -> dict[str, Any]:
    if provider == "openrouter":
        return await _openrouter(http, token)
    if provider == "deepseek":
        return await _deepseek(http, token)
    if provider == "openai-codex":
        return await _codex(http, token)
    if provider == "xai-oauth":
        return await _xai_oauth(http, token)
    if provider == "anthropic":
        return await _anthropic(http, token)
    if provider == "zai":
        return await _zai(http, token)
    if provider == "openai":
        return await _openai(http, token)
    if provider == "groq":
        return await _header_limits(http, "https://api.groq.com/openai/v1/models", token)
    if provider == "cerebras":
        return await _header_limits(http, "https://api.cerebras.ai/v1/models", token)
    if provider == "moonshot":
        return await _moonshot(http, token)
    if provider == "minimax":
        return await _minimax(http, token)
    return {"ok": False, "reason": "adapter-pending", "metrics": []}


async def _openrouter(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    credits = await http.get("https://openrouter.ai/api/v1/credits", headers=headers)
    key = await http.get("https://openrouter.ai/api/v1/key", headers=headers)
    if credits.status_code >= 400 and key.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {credits.status_code}", "metrics": []}
    metrics: list[dict[str, Any]] = []
    if credits.status_code < 400:
        payload = credits.json()
        body = payload.get("data") if isinstance(payload, dict) else {}
        total = float((body or {}).get("total_credits") or 0)
        used = float((body or {}).get("total_usage") or 0)
        metrics.append(_metric("Credit balance", "Balance", kind="unbounded", amount=max(0.0, total - used), unit="USD", period="Wallet"))
    if key.status_code < 400:
        payload = key.json()
        body = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(body, dict) and body.get("limit_remaining") is not None:
            metrics.append(_metric("Key remaining", "Balance", kind="unbounded", amount=float(body["limit_remaining"]), unit="USD", period="Key"))
    return {"ok": True, "metrics": metrics}


async def _deepseek(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    response = await http.get(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {response.status_code}", "metrics": []}
    payload = response.json()
    infos = payload.get("balance_infos") if isinstance(payload, dict) else None
    metrics = []
    for row in infos or []:
        if not isinstance(row, dict):
            continue
        amount = row.get("total_balance") or row.get("balance")
        if amount is None:
            continue
        metrics.append(_metric("Balance", "Balance", kind="unbounded", amount=float(amount), unit=str(row.get("currency") or "USD")))
    return {"ok": bool(metrics), "metrics": metrics, "reason": None if metrics else "empty"}


async def _codex(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "OpenAI-Beta": "codex-1",
        "originator": "ai-provider-library",
        "OAI-Product-Sku": "CODEX",
    }
    account = chatgpt_account_id(token)
    if account:
        headers["ChatGPT-Account-ID"] = account
    response = await http.get("https://chatgpt.com/backend-api/wham/usage", headers=headers)
    if response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {response.status_code}", "metrics": []}
    payload = response.json()
    limit = payload.get("rate_limit") if isinstance(payload, dict) else {}
    windows = []
    if isinstance(limit, dict):
        for key in ("primary_window", "secondary_window"):
            if isinstance(limit.get(key), dict):
                windows.append(limit[key])
        extra = limit.get("windows")
        if isinstance(extra, list):
            windows.extend(item for item in extra if isinstance(item, dict))
    metrics = []
    for index, window in enumerate(windows):
        used = window.get("used_percent")
        if used is None:
            used = window.get("percent_used")
        if used is None and window.get("percent_left") is not None:
            used = 100 - float(window["percent_left"])
        if used is None:
            continue
        reset = window.get("reset_at") or window.get("resets_at") or window.get("resetAt")
        secs = window.get("limit_window_seconds") or window.get("limitWindowSeconds")
        period = _period_from_seconds(secs, "Week" if index else "5h")
        metrics.append(_metric("Usage window", "RateLimit", kind="bounded", used=float(used), limit=100, unit="percent", period=period, resets_at=str(reset) if reset else None))
    return {"ok": True, "metrics": metrics}


def _period_from_seconds(secs, fallback: str) -> str:
    try:
        value = float(secs)
    except (TypeError, ValueError):
        return fallback
    if value >= 25 * 86400:
        return "Month"
    if value >= 5 * 86400:
        return "Week"
    if value >= 20 * 3600:
        return "Day"
    if value >= 3 * 3600:
        return "5h"
    return fallback


async def _xai_oauth(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "xai-grok-cli",
        "x-grok-client-version": "0.1.0",
        "x-grok-client-identifier": "grok-shell",
        "x-grok-client-mode": "cli",
    }
    response = await http.get("https://cli-chat-proxy.grok.com/v1/billing?format=credits", headers=headers)
    if response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {response.status_code}", "metrics": []}
    payload = response.json()
    config = payload.get("config") if isinstance(payload, dict) else {}
    metrics = []
    period = config.get("currentPeriod") if isinstance(config, dict) else None
    reset = None
    if isinstance(period, dict):
        reset = period.get("end") or period.get("resetsAt")
    if isinstance(config, dict) and config.get("creditUsagePercent") is not None:
        metrics.append(_metric("Weekly credits", "RateLimit", kind="bounded", used=float(config["creditUsagePercent"]), limit=100, unit="percent", period="Week", resets_at=str(reset) if reset else None))
    return {"ok": True, "metrics": metrics}


async def _anthropic(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    response = await http.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": token, "anthropic-version": "2023-06-01", "Accept": "application/json"},
    )
    if response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {response.status_code}", "metrics": []}
    metrics = []
    remaining = response.headers.get("anthropic-ratelimit-requests-remaining")
    limit = response.headers.get("anthropic-ratelimit-requests-limit")
    if remaining is not None and limit is not None:
        used = float(limit) - float(remaining)
        metrics.append(_metric("Requests", "RateLimit", kind="bounded", used=used, limit=float(limit), unit="req", period="RPM"))
    return {"ok": True, "metrics": metrics, "reason": None if metrics else "no-wallet"}


async def _zai(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    response = await http.get(
        "https://api.z.ai/api/monitor/usage/quota/limit",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {response.status_code}", "metrics": []}
    payload = response.json()
    limits = payload.get("limits") if isinstance(payload, dict) else None
    metrics = []
    for row in limits or []:
        if not isinstance(row, dict):
            continue
        cap = row.get("usage")
        remaining = row.get("remaining")
        if cap is None or remaining is None:
            continue
        reset = row.get("nextResetTime") or row.get("next_reset_time")
        metrics.append(_metric(str(row.get("type") or "Quota"), "RateLimit", kind="bounded", used=float(cap) - float(remaining), limit=float(cap), unit="tokens", resets_at=str(reset) if reset else None))
    return {"ok": bool(metrics), "metrics": metrics}


async def _openai(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    response = await http.get(
        "https://api.openai.com/dashboard/billing/credit_grants",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Referer": "https://platform.openai.com/",
            "Origin": "https://platform.openai.com",
        },
    )
    if response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {response.status_code}", "metrics": []}
    raw = response.json()
    payload = raw if isinstance(raw, dict) else {}
    available = payload.get("total_available")
    if available is None:
        granted = payload.get("total_granted")
        used = payload.get("total_used")
        if granted is not None and used is not None:
            available = float(granted) - float(used)
    if available is None:
        return {"ok": False, "reason": "no-wallet", "metrics": []}
    return {"ok": True, "metrics": [_metric("Credit grants", "Balance", kind="unbounded", amount=float(available), unit="USD")]}


async def _header_limits(http: httpx.AsyncClient, url: str, token: str) -> dict[str, Any]:
    response = await http.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {response.status_code}", "metrics": []}
    metrics = []
    req_lim = response.headers.get("x-ratelimit-limit-requests")
    req_rem = response.headers.get("x-ratelimit-remaining-requests")
    tok_lim = response.headers.get("x-ratelimit-limit-tokens")
    tok_rem = response.headers.get("x-ratelimit-remaining-tokens")
    if req_lim is not None and req_rem is not None:
        metrics.append(_metric("Requests", "RateLimit", kind="bounded", used=float(req_lim) - float(req_rem), limit=float(req_lim), unit="req"))
    if tok_lim is not None and tok_rem is not None:
        metrics.append(_metric("Tokens", "RateLimit", kind="bounded", used=float(tok_lim) - float(tok_rem), limit=float(tok_lim), unit="tok"))
    return {"ok": bool(metrics), "metrics": metrics, "reason": None if metrics else "no-headers"}


async def _moonshot(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    response = await http.get("https://api.moonshot.ai/v1/users/me/balance", headers=headers)
    if response.status_code >= 400:
        response = await http.get("https://api.moonshot.cn/v1/users/me/balance", headers=headers)
    if response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {response.status_code}", "metrics": []}
    payload = response.json()
    body = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        body = payload if isinstance(payload, dict) else {}
    amount = body.get("available_balance", body.get("balance", body.get("total_balance")))
    if amount is None:
        return {"ok": False, "reason": "empty", "metrics": []}
    return {"ok": True, "metrics": [_metric("Balance", "Balance", kind="unbounded", amount=float(amount), unit=str(body.get("currency") or "CNY"))]}


async def _minimax(http: httpx.AsyncClient, token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    urls = [
        "https://www.minimax.io/v1/token_plan/remains",
        "https://api.minimax.io/v1/token_plan/remains",
        "https://api.minimaxi.com/v1/token_plan/remains",
    ]
    response = None
    for url in urls:
        response = await http.get(url, headers=headers)
        if response.status_code < 400:
            break
    if response is None or response.status_code >= 400:
        return {"ok": False, "reason": f"HTTP {getattr(response, 'status_code', 0)}", "metrics": []}
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    rows = data.get("model_remains") if isinstance(data.get("model_remains"), list) else [data]
    metrics = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        total = row.get("current_interval_total_count") or row.get("currentIntervalTotalCount")
        left = row.get("current_interval_usage_count") or row.get("currentIntervalUsageCount")
        reset = row.get("end_time") or row.get("endTime") or row.get("weekly_end_time")
        if total is None or left is None:
            continue
        metrics.append(_metric(str(row.get("model") or "Plan"), "RateLimit", kind="bounded", used=float(total) - float(left), limit=float(total), unit="tok", period="Interval", resets_at=str(reset) if reset else None))
    return {"ok": bool(metrics), "metrics": metrics}
