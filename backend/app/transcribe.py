from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from app.audio_jobs import job_dir, load_job, public_job, save_job
from app.chunk import chunk_job
from app.schemas import AudioTranscribeRequest


PROMPT_MAX = 800


def keyword_prompt(keywords: list[str] | None, limit: int = PROMPT_MAX) -> str:
    kept: list[str] = []
    used = 0
    for item in keywords or []:
        token = str(item or "").strip()
        if not token:
            continue
        extra = (2 if kept else 0) + len(token)
        if used + extra > limit:
            break
        kept.append(token)
        used += extra
    return ", ".join(kept)


def normalize_segments(payload: dict[str, Any], offset: float = 0.0) -> list[dict[str, Any]]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        text = str(payload.get("text") or "").strip()
        if not text:
            return []
        return [{"start": offset, "end": offset, "speaker": "SPEAKER_00", "text": text}]
    speakers: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for index, row in enumerate(raw_segments):
        if not isinstance(row, dict):
            continue
        raw = str(row.get("speaker") or row.get("speaker_id") or f"SPEAKER_{index:02d}")
        if raw not in speakers:
            speakers[raw] = f"SPEAKER_{len(speakers):02d}"
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": float(row.get("start") or 0) + offset,
            "end": float(row.get("end") or 0) + offset,
            "speaker": speakers[raw],
            "text": text,
        })
    return out


def _raise_provider(response: httpx.Response) -> None:
    try:
        body = response.json()
        detail = body.get("error", body)
    except Exception:
        detail = response.text[:400]
    raise HTTPException(status_code=502, detail=str(detail))


async def transcribe_file(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    path: Path,
    diarize: bool,
    language: str,
    keywords: list[str],
) -> dict[str, Any]:
    url = f"{endpoint.rstrip('/')}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    data: dict[str, str] = {
        "model": model,
        "language": language or "en",
    }
    if diarize and "diarize" in model:
        data["response_format"] = "diarized_json"
    else:
        data["response_format"] = "verbose_json"
    prompt = keyword_prompt(keywords)
    if prompt:
        data["prompt"] = prompt
    async with httpx.AsyncClient(timeout=180.0) as client:
        with path.open("rb") as handle:
            response = await client.post(
                url,
                headers=headers,
                data=data,
                files={"file": (path.name, handle, "application/octet-stream")},
            )
    if response.status_code >= 400:
        _raise_provider(response)
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="provider returned a non-object transcript")
    return payload


async def transcribe_job(cache_dir: Path, body: AudioTranscribeRequest) -> dict[str, Any]:
    job_id = body.job_id
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    job = load_job(cache_dir, job_id)
    chunks = (job.get("files") or {}).get("chunks") or []
    if not chunks:
        chunk_job(cache_dir, job_id, max(1, int((job.get("chunkSeconds") or 600) / 60)))
        job = load_job(cache_dir, job_id)
        chunks = (job.get("files") or {}).get("chunks") or []
    folder = job_dir(cache_dir, job_id)
    job["state"] = "transcribing"
    save_job(cache_dir, job)
    endpoint = body.endpoint or "https://api.openai.com/v1"
    model = body.model or "gpt-4o-transcribe-diarize"
    seconds = float(job.get("chunkSeconds") or 600)
    segments: list[dict[str, Any]] = []
    try:
        for index, name in enumerate(chunks):
            path = folder / "chunks" / name
            if not path.is_file():
                raise HTTPException(status_code=500, detail=f"missing chunk {name}")
            payload = await transcribe_file(
                endpoint=endpoint,
                api_key=body.api_key,
                model=model,
                path=path,
                diarize=body.diarize,
                language=body.language or "en",
                keywords=body.keywords or [],
            )
            segments.extend(normalize_segments(payload, offset=index * seconds))
        job["segments"] = segments
        job["keywords"] = [item.strip() for item in (body.keywords or []) if str(item).strip()]
        job["state"] = "diarized"
        job["error"] = None
        job["provider"] = {"id": body.provider, "model": model}
    except Exception as exc:
        job["state"] = "error"
        job["error"] = str(exc)
        save_job(cache_dir, job)
        raise
    save_job(cache_dir, job)
    return public_job(job)
