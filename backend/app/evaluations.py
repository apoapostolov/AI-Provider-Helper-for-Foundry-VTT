"""Model evaluation sources, normalization, weighting, and cache."""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.vault import first_secret

SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "models-dev",
        "label": "Models.dev",
        "url": "https://models.dev/api.json",
        "default": True,
        "weight": 0.0,
    },
    {
        "id": "benchlm",
        "label": "BenchLM.ai",
        "url": "https://benchlm.ai/data/models.json",
        "default": True,
        "weight": 0.35,
    },
    {
        "id": "artificial-analysis",
        "label": "Artificial Analysis",
        "url": "https://artificialanalysis.ai/api/v2/language/models/free",
        "default": False,
        "weight": 0.35,
    },
    {
        "id": "zeroeval",
        "label": "ZeroEval",
        "url": "https://api.zeroeval.com/stats/v1/models",
        "default": False,
        "weight": 0.10,
    },
    {
        "id": "arena",
        "label": "Arena AI",
        "url": "https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboards",
        "default": False,
        "weight": 0.20,
    },
    {
        "id": "codesota",
        "label": "CodeSOTA",
        "url": "https://www.codesota.com/api/sota/code?tier=sota",
        "default": False,
        "weight": 0.0,
    },
)
SOURCE_IDS = tuple(item["id"] for item in SOURCES)
_SOURCE_MAP = {item["id"]: item for item in SOURCES}
_PROVIDER_NAMES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gemini",
    "gemini": "gemini",
    "xai": "xai",
    "mistral": "mistral",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "alibaba": "qwen",
    "zai": "zai",
    "meta": "meta",
    "microsoft": "microsoft",
    "cohere": "cohere",
    "moonshot": "moonshot",
    "minimax": "minimax",
}
_CATEGORY_GROUPS = {
    "coding": "coding",
    "code": "coding",
    "programming": "coding",
    "swe": "coding",
    "agentic": "agentic",
    "agent": "agentic",
    "tooluse": "agentic",
    "tool_usage": "agentic",
    "creative": "creativity",
    "creativity": "creativity",
    "creativewriting": "creativity",
    "storytelling": "creativity",
    "writing": "writing",
    "longform": "writing",
    "design": "design",
    "visual": "design",
    "image": "image",
    "imagen": "image",
    "imagegeneration": "image",
    "image_generation": "image",
    "imageedit": "image_edit",
    "image_edit": "image_edit",
    "vision": "image_edit",
    "multimodalgrounded": "multimodal",
    "multimodal": "multimodal",
    "document": "multimodal",
    "knowledge": "knowledge",
    "reasoning": "reasoning",
    "math": "math",
    "scientific": "scientific",
    "science": "scientific",
    "research": "scientific",
    "multilingual": "multilingual",
    "translation": "multilingual",
    "video": "video",
    "music": "music",
    "audio": "music",
}
_CATEGORY_TAGS = {
    "coding": "top_coding",
    "agentic": "top_agentic",
    "creativity": "top_creativity",
    "writing": "top_writing",
    "design": "top_design",
    "image": "top_image",
    "image_edit": "top_image_edit",
    "multimodal": "top_multimodal",
    "knowledge": "top_knowledge",
    "reasoning": "top_reasoning",
    "math": "top_math",
    "scientific": "top_scientific",
    "multilingual": "top_multilingual",
    "video": "top_video",
    "music": "top_music",
}


def source_defaults() -> dict[str, bool]:
    return {item["id"]: bool(item["default"]) for item in SOURCES}


def source_info(cache_dir: Path) -> list[dict[str, Any]]:
    cached = load_cache(cache_dir)
    status = cached.get("sources") if isinstance(cached, dict) else {}
    if not isinstance(status, dict):
        status = {}
    return [
        {
            "id": item["id"],
            "label": item["label"],
            "url": item["url"],
            "default": item["default"],
            "weight": item["weight"],
            "loaded": bool(status.get(item["id"], {}).get("loaded")),
            "count": int(status.get(item["id"], {}).get("count") or 0),
            "updatedAt": status.get(item["id"], {}).get("updatedAt"),
            "lastAttemptAt": status.get(item["id"], {}).get("lastAttemptAt"),
            "error": status.get(item["id"], {}).get("error") or "",
        }
        for item in SOURCES
    ]


def cache_path(cache_dir: Path) -> Path:
    return cache_dir / "evaluations.json"


def load_cache(cache_dir: Path) -> dict[str, Any]:
    try:
        payload = json.loads(cache_path(cache_dir).read_text())
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache_dir: Path, payload: dict[str, Any]) -> None:
    path = cache_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    tmp.replace(path)


def canonical_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("\\", "/").split("/")[-1]
    text = re.sub(r"\b(?:preview|latest|stable|experimental|exp)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _category_key(value: Any) -> str:
    raw = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    return _CATEGORY_GROUPS.get(raw, raw)


def _cost(item: dict[str, Any]) -> dict[str, float]:
    raw = item.get("cost") if isinstance(item.get("cost"), dict) else item
    result: dict[str, float] = {}
    for out, keys in {
        "input": ("input", "inputCost", "input_cost", "prompt", "promptCost", "costIn", "input_token_price", "inputTokenPrice", "price_input"),
        "output": ("output", "outputCost", "output_cost", "completion", "completionCost", "costOut", "output_token_price", "outputTokenPrice", "price_output"),
        "cacheRead": ("cache_read", "cacheRead", "cache_read_cost", "cached"),
    }.items():
        value = _number(_first(raw, *keys))
        if value is not None and value >= 0:
            result[out] = value
    return result


def _caps(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    raw = item.get("capabilities")
    if isinstance(raw, list):
        values.extend(str(value).lower() for value in raw)
    modalities = item.get("modalities") if isinstance(item.get("modalities"), dict) else {}
    inputs = modalities.get("input") or item.get("input_modalities") or []
    outputs = modalities.get("output") or item.get("output_modalities") or []
    text = " ".join(str(value).lower() for value in [*values, *(inputs if isinstance(inputs, list) else []), *(outputs if isinstance(outputs, list) else [])])
    if "text" in text:
        values.append("chat")
    if "image" in text or "vision" in text or "visual" in text:
        values.extend(["vision"])
    output_text = " ".join(str(value).lower() for value in (outputs if isinstance(outputs, list) else []))
    if "image" in output_text:
        values.extend(["image-gen"])
    if "audio" in output_text or "music" in output_text or "lyria" in str(item.get("id") or item.get("model") or "").lower():
        values.append("music")
    if "video" in output_text or "video" in text:
        values.append("video")
    if "tool" in text or item.get("tool_call") is True:
        values.append("tools")
    if item.get("reasoning") is True:
        values.append("reasoning")
    return list(dict.fromkeys(values))


def _record(source: str, item: dict[str, Any], *, provider: str = "", score: float | None = None, category_scores: dict[str, float] | None = None, rank: int | None = None, category_ranks: dict[str, int] | None = None, annotation: bool = False) -> dict[str, Any] | None:
    model_id = _first(item, "modelId", "model_id", "canonicalModelKey", "canonical_model_key", "slug", "id", "model", "name")
    label = _first(item, "label", "model", "name", "displayName", "display_name", "model_name", "id")
    if not model_id and not label:
        return None
    aliases = [value for value in (_first(item, "id"), _first(item, "slug"), _first(item, "canonicalModelKey"), _first(item, "canonical_model_key"), _first(item, "model"), _first(item, "name"), label) if value]
    context = _number(_first(item, "contextLength", "context_length", "contextWindowTokens", "context_window_tokens", "context"))
    if context is None:
        limit = item.get("limit") if isinstance(item.get("limit"), dict) else {}
        context = _number(_first(limit, "context", "input"))
    categories = {_category_key(key): value for key, value in (category_scores or {}).items() if _number(value) is not None}
    ranks = {_category_key(key): int(value) for key, value in (category_ranks or {}).items() if _number(value) is not None}
    return {
        "key": canonical_key(model_id or label),
        "modelId": str(model_id or label),
        "label": str(label or model_id),
        "provider": provider or _provider_for(str(model_id or label)),
        "aliases": list(dict.fromkeys(str(value) for value in aliases)),
        "capabilities": _caps(item),
        "contextLength": int(context) if context is not None else None,
        "cost": _cost(item),
        "scores": {"overall": score, **categories},
        "ranks": ranks,
        "rank": int(rank) if rank is not None else None,
        "tags": [],
        "source": source,
        "annotationOnly": annotation,
    }


def _provider_for(value: str) -> str:
    first = value.lower().replace("/", "-").split("-")[0]
    return _PROVIDER_NAMES.get(first, "")


def parse_models_dev(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    out: list[dict[str, Any]] = []
    for provider_id, block in payload.items():
        if not isinstance(block, dict):
            continue
        raw = block.get("models")
        items = list(raw.values()) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            row = _record("models-dev", item, provider=str(provider_id))
            if row:
                row["modelId"] = str(item.get("id") or row["modelId"])
                row["label"] = str(item.get("name") or row["label"])
                row["description"] = str(item.get("description") or "")
                row["reasoning"] = bool(item.get("reasoning"))
                row["toolCall"] = bool(item.get("tool_call"))
                row["structuredOutput"] = bool(item.get("structured_output"))
                row["releaseDate"] = item.get("release_date")
                out.append(row)
    return out


def _items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "models", "data", "results", "leaderboards", "rankings"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _items(value)
            if nested:
                return nested
    return []


def parse_benchlm(payload: object) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _items(payload):
        scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        categories = scores.get("displayCategoryScores") if isinstance(scores.get("displayCategoryScores"), dict) else {}
        ranking = item.get("ranking") if isinstance(item.get("ranking"), dict) else {}
        row = _record(
            "benchlm",
            item,
            score=_number(_first(scores, "verifiedDisplayScore", "displayScore", "overallScore", "rawOverallScore")) or _number(_first(item, "displayScore", "provisionalDisplayScore")),
            category_scores=categories,
            rank=int(_number(_first(ranking, "overallRank")) or _number(_first(item, "overallRank")) or 0) or None,
            category_ranks=ranking.get("categoryRanks") if isinstance(ranking.get("categoryRanks"), dict) else {},
        )
        if row:
            row["coverage"] = item.get("coverage") or {}
            row["evidenceStatus"] = item.get("evidenceStatus")
            row["contextLength"] = item.get("contextWindowTokens") or row["contextLength"]
            out.append(row)
    return out


def parse_artificial_analysis(payload: object) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _items(payload):
        evaluations = item.get("evaluations") if isinstance(item.get("evaluations"), dict) else {}
        performance = item.get("performance") if isinstance(item.get("performance"), dict) else {}
        values = {**item, **evaluations}
        categories: dict[str, float] = {}
        for key, target in (
            ("coding", "coding"),
            ("artificial_analysis_coding_index", "coding"),
            ("agentic", "agentic"),
            ("artificial_analysis_agentic_index", "agentic"),
            ("creative", "creativity"),
            ("creativity", "creativity"),
            ("writing", "writing"),
            ("reasoning", "reasoning"),
            ("scientific", "scientific"),
            ("science", "scientific"),
            ("multimodal", "multimodal"),
            ("math", "math"),
            ("knowledge", "knowledge"),
            ("intelligence", "overall"),
            ("intelligence_index", "overall"),
            ("intelligenceIndex", "overall"),
            ("artificial_analysis_intelligence_index", "overall"),
        ):
            value = _number(_first(values, key, f"{key}_index", f"{key}Index"))
            if value is not None:
                categories[target] = value
        score = categories.get("overall") or _number(_first(values, "score", "overall", "index"))
        row = _record("artificial-analysis", values, score=score, category_scores=categories)
        if row:
            row["speed"] = _first(performance, "speed", "tokens_per_second", "tokensPerSecond") or _first(values, "speed", "tokens_per_second", "tokensPerSecond")
            row["latency"] = _first(performance, "latency", "time_to_first_token", "timeToFirstToken") or _first(values, "latency", "time_to_first_token", "timeToFirstToken")
            task_cost = values.get("artificial_analysis_intelligence_index_cost")
            if isinstance(task_cost, dict):
                task_cost = task_cost.get("cost_per_task")
            if isinstance(task_cost, dict):
                task_cost = _first(task_cost, "total_cost", "totalCost", "cost")
            task_cost = _number(task_cost) or _number(_first(values, "cost_per_task", "costPerTask", "avg_cost_per_task"))
            if task_cost is not None and task_cost >= 0:
                row["costPerTask"] = task_cost
                row["costPerTaskSource"] = "Artificial Analysis Intelligence Index"
            token_counts = values.get("artificial_analysis_intelligence_index_token_counts")
            if isinstance(token_counts, dict):
                tokens = _first(token_counts, "total_tokens_per_task", "output_tokens_per_task", "tokens_per_task", "totalTokensPerTask", "outputTokensPerTask")
                if _number(tokens) is not None:
                    row["tokensPerTask"] = _number(tokens)
            out.append(row)
    return out


def parse_zeroeval(payload: object) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _items(payload):
        score = _number(_first(item, "score", "rating", "elo", "overall", "trueskill"))
        rank = _number(_first(item, "rank", "overall_rank", "overallRank"))
        row = _record("zeroeval", item, score=score, rank=int(rank) if rank is not None else None)
        if row:
            out.append(row)
    return out


def parse_arena(payload: object) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    meta = payload.get("meta") if isinstance(payload, dict) and isinstance(payload.get("meta"), dict) else {}
    category = str(_first(meta, "leaderboard", "name") or "text").lower()
    for item in _items(payload):
        score = _number(_first(item, "score", "elo", "rating"))
        rank = _number(_first(item, "rank", "ranking"))
        row = _record("arena", item, score=score, category_scores={category: score} if score is not None else {}, rank=int(rank) if rank is not None else None, category_ranks={category: int(rank)} if rank is not None else {})
        if row:
            row["category"] = category
            out.append(row)
    return out


def parse_codesota(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items = []
    pick = payload.get("pick")
    if isinstance(pick, dict):
        items.append(pick)
    items.extend(item for item in payload.get("runners_up", []) if isinstance(item, dict))
    out: list[dict[str, Any]] = []
    for item in items:
        row = _record("codesota", item, annotation=True)
        if row:
            row["scores"] = {"annotation": _number(_first(item, "score"))}
            row["annotationMetric"] = item.get("score_metric")
            row["task"] = payload.get("task")
            out.append(row)
    return out


def _merge_record(target: dict[str, Any], row: dict[str, Any]) -> None:
    target["aliases"] = list(dict.fromkeys([*(target.get("aliases") or []), *(row.get("aliases") or [])]))
    target["capabilities"] = list(dict.fromkeys([*(target.get("capabilities") or []), *(row.get("capabilities") or [])]))
    target["tags"] = list(dict.fromkeys([*(target.get("tags") or []), *(row.get("tags") or [])]))
    for key in ("provider", "label", "description", "contextLength", "releaseDate", "speed", "latency", "coverage", "evidenceStatus"):
        if not target.get(key) and row.get(key):
            target[key] = row[key]
    for key in ("reasoning", "toolCall", "structuredOutput"):
        if row.get(key) is True:
            target[key] = True
    target["cost"] = {**(target.get("cost") or {}), **(row.get("cost") or {})}
    normalized_scores = {_category_key(key): value for key, value in (row.get("scores") or {}).items() if value is not None}
    target["scores"] = {**(target.get("scores") or {}), **normalized_scores}
    normalized_ranks = {_category_key(key): value for key, value in (row.get("ranks") or {}).items()}
    target["ranks"] = {
        **(target.get("ranks") or {}),
        **{key: min(int((target.get("ranks") or {}).get(key, value)), int(value)) for key, value in normalized_ranks.items()},
    }
    if row.get("rank") is not None:
        target.setdefault("leaderboardRanks", {})[row["source"]] = int(row["rank"])
        target["rank"] = min(int(target.get("rank") or row["rank"]), int(row["rank"]))
    target["sources"] = list(dict.fromkeys([*(target.get("sources") or []), row["source"]]))
    score = _number((row.get("scores") or {}).get("overall"))
    if score is not None:
        target.setdefault("sourceScoresRaw", {})[row["source"]] = score
    category_scores = {_category_key(key): value for key, value in (row.get("scores") or {}).items() if key != "overall" and _number(value) is not None}
    if category_scores:
        target.setdefault("leaderboardScoresRaw", {}).setdefault(row["source"], {}).update(category_scores)
    category_ranks = {_category_key(key): value for key, value in (row.get("ranks") or {}).items() if _number(value) is not None}
    if category_ranks:
        target.setdefault("leaderboardRanksRaw", {}).setdefault(row["source"], {}).update(category_ranks)
    if row.get("costPerTask") is not None:
        target.setdefault("costPerTaskBySource", {})[row["source"]] = row["costPerTask"]
        target["costPerTask"] = target.get("costPerTask") or row["costPerTask"]
        target["costPerTaskSource"] = target.get("costPerTaskSource") or row.get("costPerTaskSource") or row["source"]
    if row.get("tokensPerTask") is not None:
        target.setdefault("tokensPerTaskBySource", {})[row["source"]] = row["tokensPerTask"]
        target["tokensPerTask"] = target.get("tokensPerTask") or row["tokensPerTask"]
    if row.get("annotationOnly"):
        target.setdefault("annotations", []).append({"source": row["source"], "metric": row.get("annotationMetric"), "score": row.get("scores", {}).get("annotation"), "task": row.get("task")})


def _normalize_score(source: str, score: float) -> float:
    if 0 <= score <= 1:
        return round(score * 100, 2)
    if 0 <= score <= 100:
        return round(score, 2)
    if source in {"arena", "zeroeval"}:
        # Arena and many ZeroEval feeds use Elo-like scores around 1000.
        return round(100 / (1 + math.exp(-((score - 1000) / 100))), 2)
    return round(min(100, max(0, score)), 2)


def _estimate_intelligence(row: dict[str, Any]) -> float:
    # This is a transparent fallback, not a benchmark claim. It intentionally
    # does not use model age, price, provider, or marketing words in a name.
    score = 50.0
    capabilities = row.get("capabilities") or []
    if "reasoning" in capabilities:
        score += 10
    if "tools" in capabilities:
        score += 5
    if "vision" in capabilities:
        score += 3
    if row.get("structuredOutput") is True:
        score += 2
    context = _number(row.get("contextLength")) or 0
    score += min(10, math.log10(max(1, context)) - 3) if context else 0
    return round(min(95, max(20, score)), 2)


def _rank_tags(models: list[dict[str, Any]]) -> None:
    # Prefer explicit leaderboard rank. The composite score is only a fallback
    # for sources that publish an index without an overall rank.
    ranked = sorted((row for row in models if row.get("rank") is not None), key=lambda row: int(row["rank"]))
    ranked_keys = {row.get("key") for row in ranked}
    ranked.extend(sorted((row for row in models if row.get("sourceScores") and row.get("key") not in ranked_keys), key=lambda row: row.get("intelligence") or 0, reverse=True))
    recommendation_tags = {"best_in_class", "highly_recommended", "recommended"}
    for row in models:
        row["tags"] = [tag for tag in row.get("tags", []) if tag not in recommendation_tags]
    for index, row in enumerate(ranked, start=1):
        position = int(row["rank"]) if row.get("rank") is not None else index
        cost_rating = int(row.get("costRating") or 0)
        if cost_rating >= 5:
            continue
        if cost_rating == 4:
            if position <= 3:
                row["tags"].append("highly_recommended")
            elif position <= 10:
                row["tags"].append("recommended")
            continue
        if position <= 3:
            row["tags"].append("best_in_class")
        if position <= 10:
            row["tags"].append("highly_recommended")
        if position <= 20:
            row["tags"].append("recommended")
    for category, tag in _CATEGORY_TAGS.items():
        eligible = [row for row in models if _number(row.get("leaderboardScores", {}).get(category)) is not None]
        eligible.sort(key=lambda row: _number(row.get("leaderboardScores", {}).get(category)) or 0, reverse=True)
        for row in eligible[:5]:
            row["tags"].append(tag)
        for row in models:
            if _number(row.get("leaderboardRanks", {}).get(category)) is not None and int(row["leaderboardRanks"][category]) <= 5:
                row["tags"].append(tag)


def _aggregate_leaderboards(row: dict[str, Any]) -> None:
    """Merge same-kind category leaderboards with source weights and renormalization."""
    raw_by_source = row.get("leaderboardScoresRaw") or {}
    categories = sorted({category for scores in raw_by_source.values() for category in scores})
    aggregate: dict[str, float] = {}
    breakdown: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        parts: list[tuple[str, float, float, float]] = []
        for source, scores in raw_by_source.items():
            raw = _number(scores.get(category))
            weight = float(_SOURCE_MAP.get(source, {}).get("weight") or 0)
            if raw is not None and weight > 0:
                parts.append((source, raw, _normalize_score(source, raw), weight))
        total_weight = sum(weight for _, _, _, weight in parts)
        if not total_weight:
            continue
        aggregate[category] = round(sum(score * weight for _, _, score, weight in parts) / total_weight, 2)
        breakdown[category] = [{"source": source, "raw": raw, "score": score, "weight": weight} for source, raw, score, weight in parts]
    row["leaderboardScores"] = aggregate
    row["leaderboardBreakdown"] = breakdown
    row["leaderboardFormula"] = "Each comparable category normalizes source scores to 0-100, then renormalizes BenchLM 35%, Artificial Analysis 35%, Arena 20%, and ZeroEval 10% over available sources."
    rank_sources = row.get("leaderboardRanksRaw") or {}
    row["leaderboardRanks"] = {
        category: min(int(ranks[category]) for ranks in rank_sources.values() if category in ranks)
        for category in {category for ranks in rank_sources.values() for category in ranks}
    }


def _efficiency_tags(models: list[dict[str, Any]]) -> None:
    """Add exclusive efficiency tiers from quality, rank, and comparable cost."""
    cost_groups: dict[str, list[dict[str, Any]]] = {}
    for row in models:
        if not row.get("sourceScores"):
            continue
        task_cost = _number(row.get("costPerTask"))
        blend = _number(row.get("costBlend"))
        if task_cost is not None:
            row["efficiencyCost"] = task_cost
            row["efficiencyCostBasis"] = "cost-per-task"
        elif blend is not None:
            row["efficiencyCost"] = blend
            row["efficiencyCostBasis"] = "weighted-token-price"
        else:
            continue
        if row["efficiencyCostBasis"] == "weighted-token-price" and row["efficiencyCost"] > 30:
            row["efficiencyCostPoints"] = 0
            continue
        cost_groups.setdefault(row["efficiencyCostBasis"], []).append(row)

    for basis, group in cost_groups.items():
        ordered = sorted(group, key=lambda item: item["efficiencyCost"])
        size = len(ordered)
        for index, row in enumerate(ordered):
            percentile = index / max(1, size - 1)
            row["efficiencyCostPercentile"] = round(percentile, 4)
            if size >= 5:
                cost_points = 2 if percentile <= 0.10 else 1 if percentile <= 0.25 else 0
            elif basis == "cost-per-task":
                cost_points = 2 if row["efficiencyCost"] <= 0.01 else 1 if row["efficiencyCost"] <= 0.05 else 0
            else:
                cost_points = 2 if row["efficiencyCost"] <= 1 else 1 if row["efficiencyCost"] <= 3 else 0
            row["efficiencyCostPoints"] = cost_points

    for row in models:
        if not row.get("sourceScores") or row.get("efficiencyCostPoints", 0) < 1:
            continue
        intelligence = _number(row.get("intelligence")) or 0
        ranks = [int(row["rank"])] if row.get("rank") is not None else []
        ranks.extend(int(value) for value in (row.get("leaderboardRanks") or {}).values() if _number(value) is not None)
        rank = min(ranks) if ranks else None
        if rank is None:
            continue
        row["efficiencyRank"] = rank
        row["efficiencyRankBasis"] = "overall or best published leaderboard rank"
        quality_candidates = [intelligence]
        for category, category_rank in (row.get("leaderboardRanks") or {}).items():
            category_score = _number((row.get("leaderboardScores") or {}).get(category))
            if category_score is not None and int(category_rank) <= 20:
                quality_candidates.append(category_score)
        efficiency_intelligence = max(quality_candidates)
        row["efficiencyIntelligence"] = round(efficiency_intelligence, 2)
        quality_points = 2 if efficiency_intelligence >= 85 else 1 if efficiency_intelligence >= 70 else 0
        rank_points = 2 if rank <= 10 else 1 if rank <= 20 else 0
        cost_points = int(row["efficiencyCostPoints"])
        row["efficiencyScore"] = quality_points + rank_points + cost_points
        row["efficiencyFormula"] = "best evaluated overall/category score with rank <=20 (2 >=85, 1 >=70) + best leaderboard rank (2 top 10, 1 top 20) + low-cost tier (2 lowest 10% or <= threshold, 1 lowest 25% or <= threshold)"
        if efficiency_intelligence >= 85 and rank <= 10 and cost_points >= 2:
            row["tags"].append("super_efficient")
        elif efficiency_intelligence >= 80 and rank <= 20 and cost_points >= 1:
            row["tags"].append("very_efficient")
        elif efficiency_intelligence >= 70 and rank <= 20 and cost_points >= 1:
            row["tags"].append("efficient")


def combine_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in records:
        key = row.get("key") or canonical_key(row.get("modelId"))
        if not key:
            continue
        target = grouped.setdefault(key, {"key": key, "modelId": row.get("modelId"), "label": row.get("label"), "tags": [], "sources": []})
        _merge_record(target, row)
    for row in grouped.values():
        _aggregate_leaderboards(row)
        source_scores: list[tuple[str, float, float, float]] = []
        for source, raw_score in (row.get("sourceScoresRaw") or {}).items():
            weight = float(_SOURCE_MAP.get(source, {}).get("weight") or 0)
            raw_score = _number(raw_score)
            if raw_score is not None and weight > 0:
                normalized = _normalize_score(source, raw_score)
                source_scores.append((source, raw_score, normalized, weight))
        total_weight = sum(weight for _, _, _, weight in source_scores)
        row["sourceScores"] = {source: normalized for source, _, normalized, _ in source_scores}
        row["intelligenceBreakdown"] = [{"source": source, "raw": raw, "score": normalized, "weight": weight} for source, raw, normalized, weight in source_scores]
        row["intelligence"] = round(sum(score * weight for _, _, score, weight in source_scores) / total_weight, 2) if total_weight else _estimate_intelligence(row)
        row["intelligenceSources"] = len(source_scores)
        row["intelligenceSource"] = "evaluated" if source_scores else "estimated"
        row["intelligenceMethod"] = "weighted-leaderboards" if source_scores else "metadata-heuristic"
        row["intelligenceFormula"] = "Weighted normalized leaderboard scores: BenchLM 35%, Artificial Analysis 35%, Arena 20%, ZeroEval 10%." if source_scores else "50 + reasoning 10 + tools 5 + vision 3 + structured output 2 + context scale up to 10; no price, age, provider, or model-name bonus."
        row["intelligenceEstimated"] = not bool(source_scores)
        cost = row.get("cost") or {}
        input_cost = _number(cost.get("input"))
        output_cost = _number(cost.get("output"))
        row["costIn"] = input_cost
        row["costOut"] = output_cost
        row["costBlend"] = round(input_cost * 0.4 + output_cost * 0.6, 6) if input_cost is not None and output_cost is not None else input_cost if input_cost is not None else output_cost
        capability_tags = {"image-gen": "image", "image-edit": "image_edit"}
        row["tags"] = list(dict.fromkeys([*(row.get("tags") or []), *[capability_tags.get(cap, cap) for cap in row.get("capabilities", [])]]))
    _efficiency_tags(list(grouped.values()))
    for row in grouped.values():
        value = row.get("costBlend")
        if value is None:
            row["costRating"] = None
            row["costLabel"] = ""
            continue
        # Fixed effective-price bands keep the display stable as sources load.
        # Blend assumes output tokens cost more often and matter more in use.
        rating = 1 if value <= 1 else 2 if value <= 3 else 3 if value <= 8 else 4 if value <= 20 else 5 if value <= 30 else 6
        row["costRating"] = rating
        row["costLabel"] = "$" * rating
    _rank_tags(list(grouped.values()))
    for row in grouped.values():
        row["tags"] = list(dict.fromkeys(row.get("tags") or []))
    return sorted(grouped.values(), key=lambda row: (-(row.get("intelligence") or -1), str(row.get("label") or "").lower()))


def _api_key(name: str) -> str:
    return str(os.environ.get(name) or "")


async def _get_json(http: httpx.AsyncClient, url: str, *, headers: dict[str, str] | None = None) -> object:
    response = await http.get(url, headers=headers or {"Accept": "application/json"})
    response.raise_for_status()
    return response.json()


async def _arena_mirror_rows(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    raw_base = "https://raw.githubusercontent.com/oolong-tea-2026/arena-ai-leaderboards/main/data"
    latest = await _get_json(http, f"{raw_base}/latest.json")
    text = json.dumps(latest) if isinstance(latest, (dict, list)) else str(latest)
    match = re.search(r"20\d{2}-\d{2}-\d{2}", text)
    date = match.group(0) if match else None
    if not date:
        return []
    rows: list[dict[str, Any]] = []
    for name in ("text", "code", "vision", "document", "image-edit", "text-to-image", "agent"):
        try:
            payload = await _get_json(http, f"{raw_base}/{date}/{name}.json")
            parsed = parse_arena(payload)
            for row in parsed:
                row["category"] = name
                row["ranks"] = {name: row.get("rank")} if row.get("rank") is not None else row.get("ranks", {})
            rows.extend(parsed)
        except (httpx.HTTPError, ValueError):
            continue
    return rows


async def fetch_source(source_id: str, http: httpx.AsyncClient, cache_dir: Path | None = None, api_key: str = "") -> list[dict[str, Any]]:
    if source_id == "models-dev":
        return parse_models_dev(await _get_json(http, _SOURCE_MAP[source_id]["url"]))
    if source_id == "benchlm":
        return parse_benchlm(await _get_json(http, _SOURCE_MAP[source_id]["url"]))
    if source_id == "artificial-analysis":
        key = api_key or _api_key("ARTIFICIAL_ANALYSIS_API_KEY") or (first_secret(cache_dir, "artificial-analysis") if cache_dir else "")
        headers = {"Accept": "application/json", **({"x-api-key": key} if key else {})}
        return parse_artificial_analysis(await _get_json(http, f'{_SOURCE_MAP[source_id]["url"]}?page_size=200', headers=headers))
    if source_id == "zeroeval":
        key = _api_key("ZEROEVAL_API_KEY")
        headers = {"Accept": "application/json", **({"Authorization": f"Bearer {key}", "x-api-key": key} if key else {})}
        return parse_zeroeval(await _get_json(http, _SOURCE_MAP[source_id]["url"], headers=headers))
    if source_id == "arena":
        try:
            index = await _get_json(http, _SOURCE_MAP[source_id]["url"])
            names = [str(item.get("name") or item.get("slug") or "text") for item in _items(index)]
        except (httpx.HTTPError, ValueError):
            index = {}
            names = []
        if not names:
            names = ["text", "code", "vision", "document", "image-edit"]
        rows: list[dict[str, Any]] = []
        for name in names[:12]:
            url = f"https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboard?name={name}"
            try:
                rows.extend(parse_arena(await _get_json(http, url)))
            except (httpx.HTTPError, ValueError):
                continue
        return rows or await _arena_mirror_rows(http)
    if source_id == "codesota":
        rows: list[dict[str, Any]] = []
        for task in ("code", "document-ocr", "agentic", "image-edit"):
            try:
                rows.extend(parse_codesota(await _get_json(http, f"https://www.codesota.com/api/sota/{task}?tier=sota")))
            except (httpx.HTTPError, ValueError):
                continue
        return rows
    raise ValueError(f"Unknown evaluation source: {source_id}")


async def refresh_source(cache_dir: Path, source_id: str, enabled_sources: set[str] | None = None, api_key: str = "") -> dict[str, Any]:
    if source_id not in _SOURCE_MAP:
        raise ValueError(f"Unknown evaluation source: {source_id}")
    cache = load_cache(cache_dir)
    existing = cache.get("records") if isinstance(cache.get("records"), list) else []
    raw = list(existing)
    status = cache.get("sources") if isinstance(cache.get("sources"), dict) else {}
    previous = status.get(source_id) if isinstance(status.get(source_id), dict) else {}
    attempted_at = datetime.now(timezone.utc).isoformat()
    downloaded_at = cache.get("updatedAt")
    success = False
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as http:
            rows = await fetch_source(source_id, http, cache_dir, api_key)
        if not rows:
            raise ValueError("source returned no model records")
        raw = [row for row in existing if row.get("source") != source_id]
        raw.extend(rows)
        downloaded_at = attempted_at
        success = True
        status[source_id] = {"loaded": True, "count": len(rows), "updatedAt": downloaded_at, "lastAttemptAt": attempted_at, "error": ""}
    except Exception as exc:
        # Keep the last successful records. A failed refresh must not turn a
        # soft ban or quota response into an empty catalog.
        status[source_id] = {
            **previous,
            "loaded": bool(previous.get("loaded")),
            "count": int(previous.get("count") or 0),
            "updatedAt": previous.get("updatedAt"),
            "lastAttemptAt": attempted_at,
            "error": str(exc)[:240],
        }
    models = combine_records(_enabled_records(raw, enabled_sources))
    payload = {"updatedAt": downloaded_at, "sources": status, "records": raw, "models": combine_records(raw)}
    save_cache(cache_dir, payload)
    return {"ok": success, "source": source_id, "status": status[source_id], "models": models, "sources": source_info(cache_dir), "enabledSources": sorted(enabled_sources) if enabled_sources is not None else None}


def _enabled_records(records: list[dict[str, Any]], enabled_sources: set[str] | None) -> list[dict[str, Any]]:
    if enabled_sources is None:
        return records
    return [row for row in records if row.get("source") in enabled_sources]


def public_payload(cache_dir: Path, enabled_sources: set[str] | None = None) -> dict[str, Any]:
    cache = load_cache(cache_dir)
    records = cache.get("records") if isinstance(cache.get("records"), list) else []
    records = _enabled_records(records, enabled_sources)
    return {"ok": True, "updatedAt": cache.get("updatedAt"), "sources": source_info(cache_dir), "enabledSources": sorted(enabled_sources) if enabled_sources is not None else None, "models": combine_records(records)}


def match_model(model: dict[str, Any], evaluations: list[dict[str, Any]]) -> dict[str, Any] | None:
    exact = {canonical_key(model.get("id")), canonical_key(model.get("name"))}
    exact.discard("")
    labels = {canonical_key(model.get("label"))}
    labels.discard("")

    def aliases_for(evaluation: dict[str, Any]) -> set[str]:
        aliases = {canonical_key(evaluation.get("key")), canonical_key(evaluation.get("modelId"))}
        aliases.update(canonical_key(value) for value in evaluation.get("aliases", []))
        return {value for value in aliases if value}

    def prefer_evaluated(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        return sorted(items, key=lambda item: (bool(item.get("sourceScores")), item.get("rank") is not None, item.get("intelligence") or 0), reverse=True)[0] if items else None

    exact_matches = [evaluation for evaluation in evaluations if exact & aliases_for(evaluation)]
    match = prefer_evaluated(exact_matches)
    if match:
        return match
    label_matches = [evaluation for evaluation in evaluations if labels & aliases_for(evaluation) or labels.intersection({canonical_key(evaluation.get("label"))})]
    return prefer_evaluated(label_matches)


def _apply_evaluation(model: dict[str, Any], evaluation: dict[str, Any] | None) -> dict[str, Any]:
    if evaluation:
        model["evaluation"] = evaluation
        for key in ("intelligence", "intelligenceSource", "intelligenceMethod", "intelligenceFormula", "costIn", "costOut", "costRating", "costLabel", "costPerTask", "costPerTaskSource", "tokensPerTask", "efficiencyScore", "efficiencyIntelligence", "efficiencyFormula", "efficiencyCostBasis", "efficiencyCostPercentile", "efficiencyRank", "efficiencyRankBasis"):
            if evaluation.get(key) is not None:
                model[key] = evaluation[key]
        model["tags"] = list(dict.fromkeys([*(model.get("tags") or []), *(evaluation.get("tags") or [])]))
        if int(evaluation.get("costRating") or 0) >= 4:
            model["recommended"] = False
        return model
    model["intelligence"] = model.get("intelligence") or _estimate_intelligence(model)
    model["intelligenceSource"] = model.get("intelligenceSource") or "estimated"
    model["intelligenceMethod"] = "metadata-heuristic"
    model["intelligenceFormula"] = "50 + reasoning 10 + tools 5 + vision 3 + structured output 2 + context scale up to 10; no price, age, provider, or model-name bonus."
    input_cost = _number(model.get("costIn"))
    output_cost = _number(model.get("costOut"))
    blend = input_cost * 0.4 + output_cost * 0.6 if input_cost is not None and output_cost is not None else input_cost if input_cost is not None else output_cost
    if blend is not None:
        model["costRating"] = 1 if blend <= 1 else 2 if blend <= 3 else 3 if blend <= 8 else 4 if blend <= 20 else 5 if blend <= 30 else 6
        model["costLabel"] = "$" * model["costRating"]
        if model["costRating"] >= 4:
            model["recommended"] = False
    capability_tags = {"image-gen": "image", "image-edit": "image_edit", "music": "music", "video": "video"}
    model["tags"] = list(dict.fromkeys([*(model.get("tags") or []), *[capability_tags.get(cap, cap) for cap in model.get("capabilities") or []]]))
    return model


def enrich_catalog_rows(rows: list[dict[str, Any]], cache_dir: Path, enabled_sources: set[str] | None = None) -> list[dict[str, Any]]:
    evaluations = public_payload(cache_dir, enabled_sources).get("models") or []
    for provider in rows:
        models = provider.get("models") if isinstance(provider.get("models"), list) else []
        for model in models:
            _apply_evaluation(model, match_model(model, evaluations))
    return rows


def enrich_query_models(models: list[dict[str, Any]], cache_dir: Path, enabled_sources: set[str] | None = None) -> list[dict[str, Any]]:
    evaluations = public_payload(cache_dir, enabled_sources).get("models") or []
    return [_apply_evaluation(model, match_model({"id": model.get("model"), "label": model.get("label")}, evaluations)) for model in models]
