from __future__ import annotations

import wave
from pathlib import Path

from app.transcribe import keyword_prompt, normalize_segments


def _wav(path: Path) -> None:
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)


def test_import_and_get_job(client, tmp_path: Path) -> None:
    src = tmp_path / "table.wav"
    _wav(src)
    response = client.post("/v1/audio/import", json={"consumerId": "session-transcripts", "path": str(src)})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "imported"
    assert body["jobId"]
    assert body["sourcePath"] == "table.wav"
    job_id = body["jobId"]
    fetched = client.get(f"/v1/audio/jobs/{job_id}")
    assert fetched.status_code == 200
    assert fetched.json()["jobId"] == job_id
    deleted = client.delete(f"/v1/audio/jobs/{job_id}")
    assert deleted.status_code == 200
    missing = client.get(f"/v1/audio/jobs/{job_id}")
    assert missing.status_code == 404


def test_import_rejects_missing_file(client) -> None:
    response = client.post("/v1/audio/import", json={"path": "C:/no-such-session.wav"})
    assert response.status_code == 400


def test_chunk_uses_ffmpeg_hook(client, tmp_path: Path, monkeypatch) -> None:
    from app import chunk as chunk_mod

    src = tmp_path / "table.wav"
    _wav(src)
    imported = client.post("/v1/audio/import", json={"path": str(src)}).json()
    job_id = imported["jobId"]

    def fake_run(args: list[str]) -> None:
        out_dir = Path(args[-1]).parent
        (out_dir / "000.mp3").write_bytes(b"id3")

    monkeypatch.setattr(chunk_mod, "ffmpeg_bin", lambda: "ffmpeg")
    monkeypatch.setattr(chunk_mod, "run_ffmpeg", fake_run)
    response = client.post("/v1/audio/chunk", json={"jobId": job_id, "chunkMinutes": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "chunked"
    assert body["files"]["chunks"] == ["000.mp3"]


def test_transcribe_mocked_provider(client, tmp_path: Path, monkeypatch) -> None:
    from app import chunk as chunk_mod
    from app import transcribe as transcribe_mod

    src = tmp_path / "table.wav"
    _wav(src)
    imported = client.post("/v1/audio/import", json={"path": str(src)}).json()
    job_id = imported["jobId"]

    def fake_run(args: list[str]) -> None:
        out_dir = Path(args[-1]).parent
        (out_dir / "000.mp3").write_bytes(b"id3")

    captured: dict = {}

    async def fake_file(**kwargs):
        captured.update(kwargs)
        return {
            "segments": [
                {"start": 0.0, "end": 1.2, "speaker": "A", "text": "We ride at dawn."}
            ]
        }

    monkeypatch.setattr(chunk_mod, "ffmpeg_bin", lambda: "ffmpeg")
    monkeypatch.setattr(chunk_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(transcribe_mod, "transcribe_file", fake_file)
    response = client.post(
        "/v1/audio/transcribe",
        json={
            "provider": "openai",
            "job_id": job_id,
            "api_key": "sk-test",
            "model": "gpt-4o-transcribe-diarize",
            "keywords": ["Thistle", "Blackwater"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "diarized"
    assert body["segments"][0]["speaker"] == "SPEAKER_00"
    assert body["segments"][0]["text"] == "We ride at dawn."
    assert captured.get("keywords") == ["Thistle", "Blackwater"]
    assert body.get("keywords") == ["Thistle", "Blackwater"]


def test_keyword_prompt_caps() -> None:
    prompt = keyword_prompt(["Thistle", "", "Blackwater Keep of the North"], limit=20)
    assert prompt == "Thistle"
    assert len(prompt) <= 20


def test_normalize_segments_offsets() -> None:
    rows = normalize_segments(
        {"segments": [{"start": 1, "end": 2, "speaker": "X", "text": "Hi"}]},
        offset=600,
    )
    assert rows == [{"start": 601.0, "end": 602.0, "speaker": "SPEAKER_00", "text": "Hi"}]


def test_catalog_includes_transcription(client) -> None:
    response = client.get("/v1/catalog", params={"capability": "transcription"})
    body = response.json()
    ids = {row["id"] for row in body["providers"]}
    assert "openai" in ids
    models = {model["id"] for row in body["providers"] for model in row.get("models") or []}
    assert "gpt-4o-transcribe-diarize" in models
