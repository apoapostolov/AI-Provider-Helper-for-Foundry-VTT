from __future__ import annotations

from app.capabilities import capabilities_from_architecture, capabilities_from_pipeline_tag
from app.catalog import filter_catalog, seed_catalog


def test_architecture_vision() -> None:
    caps = capabilities_from_architecture({
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
    })
    assert caps == ["chat", "vision"]


def test_media_modalities() -> None:
    assert capabilities_from_architecture({"output_modalities": ["audio"]}) == ["music"]
    assert capabilities_from_architecture({"output_modalities": ["video"]}) == ["video"]
    caps = capabilities_from_architecture({
        "input_modalities": ["audio"],
        "output_modalities": ["text"],
    })
    assert "transcription" in caps


def test_pipeline_tags() -> None:
    assert capabilities_from_pipeline_tag("text-to-image") == ["image-gen"]
    assert capabilities_from_pipeline_tag("image-text-to-text") == ["chat", "vision"]
    assert capabilities_from_pipeline_tag("automatic-speech-recognition") == ["transcription"]


def test_filter_catalog_vision() -> None:
    rows = filter_catalog(seed_catalog(), "vision")
    ids = {row["id"] for row in rows}
    assert "openai" in ids
    assert "ollama" in ids
    assert all("vision" in row["capabilities"] for row in rows)
