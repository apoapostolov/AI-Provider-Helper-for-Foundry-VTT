from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.audio_jobs import job_dir, load_job, new_job_id, now_iso, public_job, save_job
from app.chunk import ffmpeg_bin, run_ffmpeg

PREFERRED = (
    "discord.exe",
    "discordcanary.exe",
    "discordptb.exe",
    "chrome.exe",
    "firefox.exe",
    "obs64.exe",
)

_running: dict[str, subprocess.Popen[str]] = {}


def capture_bin() -> Path | None:
    env = os.environ.get("APL_SESSION_CAPTURE", "").strip()
    if env:
        path = Path(env)
        return path if path.is_file() else None
    here = Path(__file__).resolve()
    repo = here.parents[2]
    candidates = [
        repo / "session-capture.exe",
        repo / "native" / "session-capture" / "publish" / "session-capture.exe",
        repo / "native" / "session-capture" / "bin" / "Release" / "net8.0-windows" / "win-x64" / "session-capture.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    found = shutil.which("session-capture")
    return Path(found) if found else None


def capture_available() -> bool:
    return capture_bin() is not None


def _cmd(exe: Path, *args: str) -> list[str]:
    if exe.suffix.lower() == ".py":
        return [sys.executable, str(exe), *args]
    return [str(exe), *args]


def _run_list(exe: Path) -> dict[str, Any]:
    result = subprocess.run(
        _cmd(exe, "list"),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "session-capture list failed").strip().splitlines()
        raise HTTPException(status_code=500, detail=detail[-1] if detail else "session-capture list failed")
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="session-capture list returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="session-capture list returned invalid JSON")
    return data


def list_devices() -> dict[str, Any]:
    exe = capture_bin()
    if not exe:
        return {
            "ok": True,
            "captureAvailable": False,
            "devices": [],
            "sessions": [],
            "capture": [],
        }
    data = _run_list(exe)
    sessions = list(data.get("sessions") or [])
    devices = list(data.get("devices") or [])
    return {
        "ok": True,
        "captureAvailable": True,
        "devices": devices,
        "sessions": sessions,
        "capture": devices,
        "sidecar": exe.name,
    }


def pick_session(sessions: list[dict[str, Any]], preferred: str = "") -> dict[str, Any]:
    wanted = (preferred or "Discord.exe").lower()
    if not wanted.endswith(".exe"):
        wanted += ".exe"
    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in sessions:
        name = str(row.get("name") or "").lower()
        if name and not name.endswith(".exe"):
            name += ".exe"
        peak = float(row.get("peak") or 0)
        score = peak
        if name == wanted:
            score += 1.0
        if name in PREFERRED:
            score += 0.25
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        raise HTTPException(status_code=400, detail="no render session to capture")
    return ranked[0][1]


def start_record(
    cache_dir: Path,
    consumer_id: str = "",
    process_id: int | None = None,
    include_mic: bool = True,
    preferred_process: str = "",
) -> dict[str, Any]:
    exe = capture_bin()
    if not exe:
        raise HTTPException(status_code=501, detail="capture sidecar is not in this build")
    listing = _run_list(exe)
    sessions = list(listing.get("sessions") or [])
    chosen = None
    if process_id:
        chosen = next((row for row in sessions if int(row.get("pid") or 0) == int(process_id)), None)
        if chosen is None:
            chosen = {"pid": int(process_id), "name": str(process_id), "peak": 0}
    else:
        chosen = pick_session(sessions, preferred_process)
    pid = int(chosen.get("pid") or 0)
    if pid <= 0:
        raise HTTPException(status_code=400, detail="processId is required")
    job_id = new_job_id()
    folder = job_dir(cache_dir, job_id)
    folder.mkdir(parents=True, exist_ok=True)
    args = ["record", "--pid", str(pid), "--out", str(folder)]
    if include_mic:
        args.extend(["--mic", "default"])
    else:
        args.append("--no-mic")
    proc = subprocess.Popen(
        _cmd(exe, *args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _running[job_id] = proc
    job = {
        "id": job_id,
        "state": "recording",
        "consumerId": consumer_id or "",
        "sourcePath": "",
        "createdAt": now_iso(),
        "startedAt": int(time.time() * 1000),
        "stoppedAt": 0,
        "processId": pid,
        "processName": str(chosen.get("name") or ""),
        "includeMic": bool(include_mic),
        "sidecarPid": proc.pid,
        "chunkSeconds": 600,
        "files": {"source": "", "chunks": [], "remote": "remote.wav", "mic": "mic.wav" if include_mic else ""},
        "duration": 0,
        "segments": [],
        "error": None,
        "peak": float(chosen.get("peak") or 0),
    }
    save_job(cache_dir, job)
    return public_job(job)


def _alive(job_id: str) -> bool:
    proc = _running.get(job_id)
    return bool(proc and proc.poll() is None)


def record_status(cache_dir: Path, job_id: str) -> dict[str, Any]:
    job = load_job(cache_dir, job_id)
    status_path = job_dir(cache_dir, job_id) / "status.json"
    if status_path.is_file():
        try:
            extra = json.loads(status_path.read_text(encoding="utf-8"))
            job["peak"] = extra.get("peak", job.get("peak"))
            job["elapsedMs"] = extra.get("elapsedMs")
            job["processName"] = extra.get("process") or job.get("processName")
        except json.JSONDecodeError:
            pass
    job["recording"] = job.get("state") == "recording" and _alive(job_id)
    if job.get("state") == "recording" and not _alive(job_id):
        proc = _running.get(job_id)
        err = ""
        if proc and proc.stderr:
            err = (proc.stderr.read() or "").strip()
        job["state"] = "error"
        job["error"] = err or "capture sidecar exited"
        save_job(cache_dir, job)
    return public_job(job)


def _mix(folder: Path, include_mic: bool) -> Path:
    remote = folder / "remote.wav"
    mic = folder / "mic.wav"
    mix = folder / "mix.flac"
    source = folder / "source.flac"
    if not remote.is_file() or remote.stat().st_size < 44:
        raise HTTPException(status_code=500, detail="remote.wav was not written")
    binary = ffmpeg_bin()
    if include_mic and mic.is_file() and mic.stat().st_size > 44:
        run_ffmpeg([
            binary,
            "-y",
            "-i",
            str(remote),
            "-i",
            str(mic),
            "-filter_complex",
            "amix=inputs=2:duration=longest:dropout_transition=0",
            "-ac",
            "1",
            "-ar",
            "48000",
            str(mix),
        ])
    else:
        run_ffmpeg([
            binary,
            "-y",
            "-i",
            str(remote),
            "-ac",
            "1",
            "-ar",
            "48000",
            str(mix),
        ])
    shutil.copy2(mix, source)
    return source


def stop_record(cache_dir: Path, job_id: str) -> dict[str, Any]:
    job = load_job(cache_dir, job_id)
    folder = job_dir(cache_dir, job_id)
    stop = folder / "stop"
    stop.write_text("1", encoding="utf-8")
    proc = _running.get(job_id)
    if proc and proc.poll() is None:
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    include_mic = bool(job.get("includeMic"))
    try:
        source = _mix(folder, include_mic)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    job["state"] = "imported"
    job["stoppedAt"] = int(time.time() * 1000)
    job["sourcePath"] = str(source)
    job["files"] = {
        **(job.get("files") or {}),
        "source": source.name,
        "mix": "mix.flac",
        "remote": "remote.wav",
        "mic": "mic.wav" if include_mic else "",
    }
    job["error"] = None
    save_job(cache_dir, job)
    _running.pop(job_id, None)
    return public_job(job)
