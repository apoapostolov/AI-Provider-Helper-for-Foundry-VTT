from __future__ import annotations

from pathlib import Path

from app.query import build_query
from app.taxonomy import taxonomy_from_openrouter
from app.vault import upsert_credential


def test_query_image_edit_and_grant(tmp_path: Path) -> None:
    upsert_credential(tmp_path, provider_id="openai", label="Tiles", grants=["imaginary-tiles"], secret="sk")
    payload = build_query(consumer_id="imaginary-tiles", capability="image-edit", cache_dir=tmp_path)
    ids = {row["id"] for row in payload["providers"]}
    assert "openai" in ids
    assert "ollama" not in ids
    openai = next(row for row in payload["providers"] if row["id"] == "openai")
    assert openai["granted"] is True
    assert all(model["imageEdit"] for model in openai["models"])


def test_openrouter_taxonomy_image_edit() -> None:
    row = taxonomy_from_openrouter({
        "id": "openai/gpt-image-1",
        "name": "GPT Image 1",
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
        "pricing": {"prompt": "0.000005", "completion": "0.00004", "image": "0.04"},
    })
    assert row["imageGen"] is True
    assert row["imageEdit"] is True
    assert row["vision"] is False
    assert row["costIn"] == 5
    assert row["costImage"] == 0.04
