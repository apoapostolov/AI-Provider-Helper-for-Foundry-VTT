"""Native STT adapters for diarized batch transcription.

Protocol logic is ported from public API docs (and the BSD-2 pipecat adapters
as a cross-check). These are callable HTTP helpers, not a pipeline framework.
Each adapter returns a payload that `normalize_segments()` already understands:
`{"segments": [{"start": float, "end": float, "speaker": str, "text": str}, ...]}`.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

NATIVE_PROVIDERS = frozenset({"deepgram", "gladia", "speechmatics", "assemblyai"})

POLL_INTERVAL = 1.5
POLL_TIMEOUT = 180.0


def _raise(response: httpx.Response) -> None:
    try:
        body = response.json()
        detail = body.get("error", body) if isinstance(body, dict) else body
    except Exception:
        detail = response.text[:400]
    raise HTTPException(status_code=502, detail=str(detail))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def group_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse consecutive same-speaker words into utterance segments."""
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for word in words:
        text = str(word.get("text") or word.get("punctuated_word") or word.get("word") or "").strip()
        if not text:
            continue
        speaker = str(word.get("speaker") if word.get("speaker") is not None else "SPEAKER_00")
        start = _as_float(word.get("start"))
        end = _as_float(word.get("end"), start)
        if current and current["speaker"] == speaker:
            current["end"] = max(current["end"], end)
            current["text"] = f"{current['text']} {text}".strip()
            continue
        if current:
            segments.append(current)
        current = {"start": start, "end": end, "speaker": speaker, "text": text}
    if current:
        segments.append(current)
    return segments


def segments_from_deepgram(payload: dict[str, Any]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    channels = ((payload.get("results") or {}).get("channels") or [])
    for channel in channels:
        alts = channel.get("alternatives") or []
        if not alts:
            continue
        for row in alts[0].get("words") or []:
            if not isinstance(row, dict):
                continue
            words.append({
                "text": row.get("punctuated_word") or row.get("word") or "",
                "speaker": row.get("speaker", 0),
                "start": row.get("start", 0),
                "end": row.get("end", 0),
            })
        if not words:
            text = str(alts[0].get("transcript") or "").strip()
            if text:
                return [{"start": 0.0, "end": 0.0, "speaker": "0", "text": text}]
    return group_words(words)


def segments_from_gladia(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") or payload
    transcription = result.get("transcription") or {}
    utterances = transcription.get("utterances") or result.get("utterances") or []
    out: list[dict[str, Any]] = []
    for row in utterances:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": _as_float(row.get("start")),
            "end": _as_float(row.get("end")),
            "speaker": str(row.get("speaker") if row.get("speaker") is not None else "0"),
            "text": text,
        })
    if out:
        return out
    text = str(transcription.get("full_transcript") or payload.get("text") or "").strip()
    return [{"start": 0.0, "end": 0.0, "speaker": "0", "text": text}] if text else []


def segments_from_assemblyai(payload: dict[str, Any]) -> list[dict[str, Any]]:
    utterances = payload.get("utterances") or []
    out: list[dict[str, Any]] = []
    for row in utterances:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        start_ms = _as_float(row.get("start"))
        end_ms = _as_float(row.get("end"), start_ms)
        # AssemblyAI timestamps are milliseconds.
        scale = 0.001 if start_ms >= 20 or end_ms >= 20 else 1.0
        out.append({
            "start": start_ms * scale,
            "end": end_ms * scale,
            "speaker": str(row.get("speaker") if row.get("speaker") is not None else "A"),
            "text": text,
        })
    if out:
        return out
    text = str(payload.get("text") or "").strip()
    return [{"start": 0.0, "end": 0.0, "speaker": "A", "text": text}] if text else []


def segments_from_speechmatics(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results") or []
    words: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        if row.get("type") not in (None, "word"):
            continue
        alts = row.get("alternatives") or [{}]
        alt = alts[0] if alts else {}
        content = str(alt.get("content") or "").strip()
        if not content:
            continue
        words.append({
            "text": content,
            "speaker": alt.get("speaker") or row.get("speaker") or "UU",
            "start": row.get("start_time", 0),
            "end": row.get("end_time", 0),
        })
    return group_words(words)


def wrapped(segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {"segments": segments}


async def _poll(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    *,
    done: Callable[[dict[str, Any]], bool],
    failed: Callable[[dict[str, Any]], str | None],
) -> dict[str, Any]:
    deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT
    last: dict[str, Any] = {}
    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            _raise(response)
        last = response.json()
        if not isinstance(last, dict):
            raise HTTPException(status_code=502, detail="provider poll returned a non-object")
        error = failed(last)
        if error:
            raise HTTPException(status_code=502, detail=error)
        if done(last):
            return last
        await asyncio.sleep(POLL_INTERVAL)
    raise HTTPException(status_code=504, detail="transcription timed out waiting for provider")


def _audio_headers(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
    }.get(suffix, "application/octet-stream")


async def transcribe_deepgram(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    path: Path,
    diarize: bool,
    language: str,
    keywords: list[str],
) -> dict[str, Any]:
    host = (endpoint or "https://api.deepgram.com").rstrip("/")
    if host.endswith("/v1"):
        host = host[:-3]
    params: dict[str, str] = {
        "model": model or "nova-3",
        "smart_format": "true",
        "punctuate": "true",
        "language": language or "en",
        "diarize": "true" if diarize else "false",
        "utterances": "true" if diarize else "false",
    }
    if keywords:
        params["keywords"] = ",".join(keywords[:20])
    url = f"{host}/v1/listen?{urlencode(params)}"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": _audio_headers(path),
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(url, headers=headers, content=path.read_bytes())
    if response.status_code >= 400:
        _raise(response)
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="deepgram returned a non-object transcript")
    return wrapped(segments_from_deepgram(payload))


async def transcribe_gladia(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    path: Path,
    diarize: bool,
    language: str,
    keywords: list[str],
) -> dict[str, Any]:
    host = (endpoint or "https://api.gladia.io").rstrip("/")
    headers = {"X-Gladia-Key": api_key}
    async with httpx.AsyncClient(timeout=180.0) as client:
        with path.open("rb") as handle:
            uploaded = await client.post(
                f"{host}/v2/upload",
                headers=headers,
                files={"audio": (path.name, handle, _audio_headers(path))},
            )
        if uploaded.status_code >= 400:
            _raise(uploaded)
        audio_url = (uploaded.json() or {}).get("audio_url")
        if not audio_url:
            raise HTTPException(status_code=502, detail="gladia upload returned no audio_url")
        body: dict[str, Any] = {
            "audio_url": audio_url,
            "diarization": bool(diarize),
            "language": language or "en",
        }
        if model:
            body["model"] = model
        if keywords:
            body["custom_vocabulary"] = True
            body["custom_vocabulary_config"] = {"vocabulary": keywords[:50]}
        started = await client.post(f"{host}/v2/pre-recorded", headers=headers, json=body)
        if started.status_code >= 400:
            _raise(started)
        started_body = started.json()
        result_url = started_body.get("result_url") or (
            f"{host}/v2/pre-recorded/{started_body.get('id')}"
        )
        done = await _poll(
            client,
            result_url,
            headers,
            done=lambda row: str(row.get("status") or "").lower() in {"done", "success"},
            failed=lambda row: (
                str(row.get("error") or row.get("message") or "gladia job failed")
                if str(row.get("status") or "").lower() in {"error", "failed"}
                else None
            ),
        )
    return wrapped(segments_from_gladia(done))


async def transcribe_assemblyai(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    path: Path,
    diarize: bool,
    language: str,
    keywords: list[str],
) -> dict[str, Any]:
    host = (endpoint or "https://api.assemblyai.com").rstrip("/")
    headers = {"Authorization": api_key}
    async with httpx.AsyncClient(timeout=180.0) as client:
        uploaded = await client.post(
            f"{host}/v2/upload",
            headers={**headers, "Content-Type": _audio_headers(path)},
            content=path.read_bytes(),
        )
        if uploaded.status_code >= 400:
            _raise(uploaded)
        audio_url = (uploaded.json() or {}).get("upload_url")
        if not audio_url:
            raise HTTPException(status_code=502, detail="assemblyai upload returned no upload_url")
        body: dict[str, Any] = {
            "audio_url": audio_url,
            "speaker_labels": bool(diarize),
            "language_code": language or "en",
        }
        if model:
            body["speech_model"] = model
        if keywords:
            body["word_boost"] = keywords[:20]
        started = await client.post(f"{host}/v2/transcript", headers=headers, json=body)
        if started.status_code >= 400:
            _raise(started)
        job_id = (started.json() or {}).get("id")
        if not job_id:
            raise HTTPException(status_code=502, detail="assemblyai returned no transcript id")
        done = await _poll(
            client,
            f"{host}/v2/transcript/{job_id}",
            headers,
            done=lambda row: str(row.get("status") or "").lower() == "completed",
            failed=lambda row: (
                str(row.get("error") or "assemblyai job failed")
                if str(row.get("status") or "").lower() in {"error", "failed"}
                else None
            ),
        )
    return wrapped(segments_from_assemblyai(done))


async def transcribe_speechmatics(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    path: Path,
    diarize: bool,
    language: str,
    keywords: list[str],
) -> dict[str, Any]:
    host = (endpoint or "https://asr.api.speechmatics.com/v2").rstrip("/")
    if host.endswith("/v2"):
        jobs_url = f"{host}/jobs"
    else:
        jobs_url = f"{host}/v2/jobs"
    headers = {"Authorization": f"Bearer {api_key}"}
    config: dict[str, Any] = {
        "type": "transcription",
        "transcription_config": {
            "language": language or "en",
            "operating_point": model or "enhanced",
            "diarization": "speaker" if diarize else "none",
        },
    }
    if keywords:
        config["transcription_config"]["additional_vocab"] = [
            {"content": token} for token in keywords[:50]
        ]
    async with httpx.AsyncClient(timeout=180.0) as client:
        with path.open("rb") as handle:
            started = await client.post(
                jobs_url,
                headers=headers,
                data={"config": json.dumps(config)},
                files={"data_file": (path.name, handle, _audio_headers(path))},
            )
        if started.status_code >= 400:
            _raise(started)
        job_id = ((started.json() or {}).get("id")
                  or ((started.json() or {}).get("job") or {}).get("id"))
        if not job_id:
            raise HTTPException(status_code=502, detail="speechmatics returned no job id")
        status_url = f"{jobs_url.rstrip('/')}/{job_id}"
        await _poll(
            client,
            status_url,
            headers,
            done=lambda row: str(
                (row.get("job") or row).get("status") or ""
            ).lower() in {"done", "success"},
            failed=lambda row: (
                str((row.get("job") or row).get("error") or "speechmatics job failed")
                if str((row.get("job") or row).get("status") or "").lower()
                in {"rejected", "failed", "error"}
                else None
            ),
        )
        transcript = await client.get(f"{status_url}/transcript", headers=headers)
        if transcript.status_code >= 400:
            _raise(transcript)
        payload = transcript.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="speechmatics returned a non-object transcript")
    return wrapped(segments_from_speechmatics(payload))


Adapter = Callable[..., Awaitable[dict[str, Any]]]

ADAPTERS: dict[str, Adapter] = {
    "deepgram": transcribe_deepgram,
    "gladia": transcribe_gladia,
    "assemblyai": transcribe_assemblyai,
    "speechmatics": transcribe_speechmatics,
}


async def transcribe_native(
    *,
    provider: str,
    endpoint: str,
    api_key: str,
    model: str,
    path: Path,
    diarize: bool,
    language: str,
    keywords: list[str],
) -> dict[str, Any]:
    adapter = ADAPTERS.get((provider or "").strip().lower())
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"unknown native stt provider: {provider}")
    return await adapter(
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        path=path,
        diarize=diarize,
        language=language,
        keywords=keywords,
    )
