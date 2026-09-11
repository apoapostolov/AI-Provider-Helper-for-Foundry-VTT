from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.audio_jobs import job_dir, load_job, public_job, save_job


def ffmpeg_bin() -> str:
    env = os.environ.get("APL_FFMPEG", "").strip()
    if env:
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError("ffmpeg is not on PATH")


def run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip().splitlines()
        raise HTTPException(status_code=500, detail=detail[-1] if detail else "ffmpeg failed")


def chunk_job(cache_dir: Path, job_id: str, chunk_minutes: int = 10) -> dict[str, Any]:
    job = load_job(cache_dir, job_id)
    folder = job_dir(cache_dir, job_id)
    source_name = (job.get("files") or {}).get("source") or ""
    source = folder / source_name
    if not source.is_file():
        raise HTTPException(status_code=400, detail="job has no source audio")
    seconds = max(60, int(chunk_minutes or 10) * 60)
    chunks = folder / "chunks"
    if chunks.exists():
        shutil.rmtree(chunks)
    chunks.mkdir(parents=True, exist_ok=True)
    pattern = str(chunks / "%03d.mp3")
    try:
        binary = ffmpeg_bin()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    run_ffmpeg([
        binary,
        "-y",
        "-i",
        str(source),
        "-f",
        "segment",
        "-segment_time",
        str(seconds),
        "-reset_timestamps",
        "1",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "96k",
        pattern,
    ])
    names = sorted(path.name for path in chunks.glob("*.mp3"))
    if not names:
        raise HTTPException(status_code=500, detail="ffmpeg wrote no chunks")
    job["chunkSeconds"] = seconds
    job["files"] = {**(job.get("files") or {}), "chunks": names}
    job["state"] = "chunked"
    job["error"] = None
    save_job(cache_dir, job)
    return public_job(job)
