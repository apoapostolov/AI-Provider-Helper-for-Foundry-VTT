from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from app.stt_providers import (
    segments_from_assemblyai,
    segments_from_deepgram,
    segments_from_gladia,
    segments_from_speechmatics,
    transcribe_deepgram,
)


def test_deepgram_groups_speakers() -> None:
    payload = {
        "results": {
            "channels": [{
                "alternatives": [{
                    "transcript": "We ride at dawn.",
                    "words": [
                        {"word": "We", "punctuated_word": "We", "start": 0.1, "end": 0.2, "speaker": 0},
                        {"word": "ride", "punctuated_word": "ride", "start": 0.2, "end": 0.4, "speaker": 0},
                        {"word": "at", "punctuated_word": "at", "start": 1.0, "end": 1.1, "speaker": 1},
                        {"word": "dawn", "punctuated_word": "dawn.", "start": 1.1, "end": 1.5, "speaker": 1},
                    ],
                }]
            }]
        }
    }
    rows = segments_from_deepgram(payload)
    assert [row["speaker"] for row in rows] == ["0", "1"]
    assert rows[0]["text"] == "We ride"
    assert rows[1]["text"] == "at dawn."
    assert rows[0]["start"] == 0.1
    assert rows[1]["end"] == 1.5


def test_gladia_utterances() -> None:
    payload = {
        "status": "done",
        "result": {
            "transcription": {
                "utterances": [
                    {"start": 0.0, "end": 1.2, "speaker": 0, "text": "We ride at dawn."},
                    {"start": 1.3, "end": 2.0, "speaker": 1, "text": "Hold."},
                ]
            }
        },
    }
    rows = segments_from_gladia(payload)
    assert len(rows) == 2
    assert rows[1]["speaker"] == "1"
    assert rows[1]["text"] == "Hold."


def test_assemblyai_ms_timestamps() -> None:
    payload = {
        "status": "completed",
        "utterances": [
            {"start": 100, "end": 1500, "speaker": "A", "text": "We ride at dawn."},
        ],
    }
    rows = segments_from_assemblyai(payload)
    assert rows == [{"start": 0.1, "end": 1.5, "speaker": "A", "text": "We ride at dawn."}]


def test_speechmatics_words() -> None:
    payload = {
        "results": [
            {"type": "word", "start_time": 0.1, "end_time": 0.3, "alternatives": [{"content": "We", "speaker": "S1"}]},
            {"type": "word", "start_time": 0.3, "end_time": 0.5, "alternatives": [{"content": "ride", "speaker": "S1"}]},
            {"type": "word", "start_time": 0.8, "end_time": 1.0, "alternatives": [{"content": "Hold", "speaker": "S2"}]},
        ]
    }
    rows = segments_from_speechmatics(payload)
    assert [row["text"] for row in rows] == ["We ride", "Hold"]
    assert [row["speaker"] for row in rows] == ["S1", "S2"]


def test_deepgram_http_adapter(tmp_path: Path, monkeypatch) -> None:
    clip = tmp_path / "000.mp3"
    clip.write_bytes(b"id3")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": {
                    "channels": [{
                        "alternatives": [{
                            "words": [
                                {"punctuated_word": "Hello.", "start": 0.0, "end": 0.4, "speaker": 0},
                            ]
                        }]
                    }]
                }
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            assert "listen" in url
            assert "diarize=true" in url
            assert kwargs["headers"]["Authorization"] == "Token dg-test"
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    payload = asyncio.run(transcribe_deepgram(
        endpoint="https://api.deepgram.com",
        api_key="dg-test",
        model="nova-3",
        path=clip,
        diarize=True,
        language="en",
        keywords=["Thistle"],
    ))
    assert payload["segments"][0]["text"] == "Hello."
