from __future__ import annotations

from pathlib import Path

from app import capture as capture_mod
from app import chunk as chunk_mod


FAKE_CAPTURE = r"""
import json
import sys
import time
import wave
from pathlib import Path

def wav(path: Path) -> None:
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)

cmd = sys.argv[1]
if cmd == "list":
    print(json.dumps({
        "ok": True,
        "devices": [{"id": "mic", "name": "Mic", "flow": "capture", "default": True}],
        "sessions": [{"pid": 4242, "name": "Discord.exe", "peak": 0.8}]
    }))
    raise SystemExit(0)
out = Path(sys.argv[sys.argv.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
wav(out / "remote.wav")
wav(out / "mic.wav")
stop = out / "stop"
status = out / "status.json"
elapsed = 0
while not stop.is_file():
    status.write_text(json.dumps({"ok": True, "pid": 4242, "process": "Discord.exe", "elapsedMs": elapsed, "peak": 0.4}), encoding="utf-8")
    time.sleep(0.05)
    elapsed += 50
raise SystemExit(0)
"""


def test_record_start_stop(client, tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "fake-capture.py"
    fake.write_text(FAKE_CAPTURE, encoding="utf-8")
    monkeypatch.setattr(capture_mod, "capture_bin", lambda: fake)

    def fake_run(args: list[str]) -> None:
        folder = Path(args[-1]).parent if args[-1].endswith(".flac") else Path(args[-1])
        if args[-1].endswith(".flac"):
            Path(args[-1]).write_bytes(b"fLaC")

    monkeypatch.setattr(chunk_mod, "ffmpeg_bin", lambda: "ffmpeg")
    monkeypatch.setattr(chunk_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(capture_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(capture_mod, "ffmpeg_bin", lambda: "ffmpeg")

    devices = client.get("/v1/audio/devices")
    assert devices.status_code == 200
    body = devices.json()
    assert body["captureAvailable"] is True
    assert body["sessions"][0]["name"] == "Discord.exe"

    started = client.post("/v1/audio/record/start", json={
        "consumerId": "session-transcripts",
        "preferredProcess": "Discord.exe",
        "includeMic": True
    })
    assert started.status_code == 200, started.text
    job = started.json()
    assert job["state"] == "recording"
    job_id = job["jobId"]
    status = client.get("/v1/audio/record/status", params={"jobId": job_id})
    assert status.status_code == 200
    stopped = client.post("/v1/audio/record/stop", json={"jobId": job_id})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["state"] == "imported"
    assert stopped.json()["files"]["source"] == "source.flac"


def test_record_without_sidecar_is_501(client, monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, "capture_bin", lambda: None)
    response = client.post("/v1/audio/record/start", json={"consumerId": "session-transcripts"})
    assert response.status_code == 501
    devices = client.get("/v1/audio/devices")
    assert devices.json()["captureAvailable"] is False
