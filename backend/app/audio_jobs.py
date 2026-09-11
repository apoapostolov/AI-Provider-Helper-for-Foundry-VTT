from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

ALLOWED_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".webm", ".mp4", ".mpeg", ".mpga"}
MAX_IMPORT_BYTES = 2 * 1024 * 1024 * 1024


def sessions_dir(cache_dir: Path) -> Path:
    path = Path(cache_dir) / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_dir(cache_dir: Path, job_id: str) -> Path:
    return sessions_dir(cache_dir) / job_id


def job_json_path(cache_dir: Path, job_id: str) -> Path:
    return job_dir(cache_dir, job_id) / "job.json"


def new_job_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_job(cache_dir: Path, job_id: str) -> dict[str, Any]:
    path = job_json_path(cache_dir, job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="unknown audio job")
    return json.loads(path.read_text(encoding="utf-8"))


def save_job(cache_dir: Path, job: dict[str, Any]) -> dict[str, Any]:
    folder = job_dir(cache_dir, job["id"])
    folder.mkdir(parents=True, exist_ok=True)
    job_json_path(cache_dir, job["id"]).write_text(
        json.dumps(job, indent=2),
        encoding="utf-8",
    )
    return job


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    data = dict(job)
    data["jobId"] = job.get("id") or ""
    source = Path(str(job.get("sourcePath") or ""))
    data["sourcePath"] = source.name
    return data


def import_audio(cache_dir: Path, path: str, consumer_id: str = "", chunk_minutes: int = 10) -> dict[str, Any]:
    src = Path(path).expanduser()
    if not src.is_file():
        raise HTTPException(status_code=400, detail="audio path is not a file")
    if src.suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="unsupported audio type")
    size = src.stat().st_size
    if size <= 0 or size > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="audio file is empty or too large")
    job_id = new_job_id()
    dest_dir = job_dir(cache_dir, job_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"source{src.suffix.lower()}"
    shutil.copy2(src, dest)
    job = {
        "id": job_id,
        "state": "imported",
        "consumerId": consumer_id or "",
        "sourcePath": str(src),
        "createdAt": now_iso(),
        "chunkSeconds": max(60, int(chunk_minutes or 10) * 60),
        "files": {
            "source": dest.name,
            "chunks": [],
        },
        "duration": 0,
        "segments": [],
        "error": None,
    }
    save_job(cache_dir, job)
    return public_job(job)


def delete_job(cache_dir: Path, job_id: str) -> None:
    folder = job_dir(cache_dir, job_id)
    if not folder.exists():
        raise HTTPException(status_code=404, detail="unknown audio job")
    shutil.rmtree(folder)
