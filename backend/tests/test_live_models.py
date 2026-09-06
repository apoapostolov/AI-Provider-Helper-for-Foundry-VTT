from __future__ import annotations

from app.live_models import infer_capabilities, merge_model_lists
from app.query import build_query
from app.scrape import flatten_models_dev, parse_models_dev


def test_infer_skips_audio_and_marks_image() -> None:
    assert infer_capabilities("whisper-1") == []
    assert "image-gen" in infer_capabilities("gpt-image-1")
    assert "vision" in infer_capabilities("claude-sonnet-4-6")
    assert infer_capabilities("text-embedding-3-small") == ["embeddings"]


def test_parse_models_dev_maps_providers() -> None:
    payload = {
        "openai": {
            "models": {
                "gpt-4o": {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                    "limit": {"context": 128000},
                    "cost": {"input": 2.5, "output": 10, "cache_read": 1.25},
                }
            }
        },
        "google": {
            "models": {
                "gemini-3-flash": {
                    "id": "gemini-3-flash",
                    "name": "Gemini 3 Flash",
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                }
            }
        },
        "openrouter": {
            "models": {
                "openai/gpt-4o": {"id": "openai/gpt-4o", "name": "GPT-4o"}
            }
        },
    }
    parsed = parse_models_dev(payload)
    assert "gpt-4o" in {row["id"] for row in parsed["openai"]}
    assert "openai-codex" in parsed
    assert parsed["gemini"][0]["id"] == "gemini-3-flash"
    assert any(row["id"] == "openai/gpt-4o" for row in parsed["openrouter"])
    gpt = next(row for row in parsed["openai"] if row["id"] == "gpt-4o")
    assert gpt["cost"]["prompt"] == 2.5
    assert "vision" in gpt["capabilities"]
    flat = flatten_models_dev(parsed)
    assert any(row["id"] == "gpt-4o" and row["costIn"] == 2.5 for row in flat)


def test_merge_live_keeps_seed_and_adds_new() -> None:
    seed = [{"id": "gpt-4o", "label": "GPT-4o", "capabilities": ["chat", "vision"]}]
    live = [
        {"id": "gpt-4o", "label": "GPT-4o Live", "cost": {"prompt": 2.5}, "live": True},
        {"id": "gpt-5.4", "label": "GPT-5.4", "capabilities": ["chat", "vision"], "live": True},
    ]
    merged = merge_model_lists(seed, live)
    ids = {row["id"] for row in merged}
    assert ids == {"gpt-4o", "gpt-5.4"}
    gpt = next(row for row in merged if row["id"] == "gpt-4o")
    assert gpt["label"] == "GPT-4o"
    assert gpt["cost"]["prompt"] == 2.5
    assert gpt["live"] is True


def test_query_merges_live_openrouter(tmp_path) -> None:
    live = [{
        "id": "google/gemini-3-flash",
        "label": "Gemini 3 Flash",
        "capabilities": ["chat", "vision"],
        "live": True,
        "source": "openrouter",
    }]
    payload = build_query(
        consumer_id="hex-atlas-survey",
        capability="vision",
        openrouter=live,
        live_by_provider={"openrouter": live},
        cache_dir=tmp_path,
    )
    orow = next(row for row in payload["providers"] if row["id"] == "openrouter")
    ids = {model["model"] for model in orow["models"]}
    assert "google/gemini-3-flash" in ids
