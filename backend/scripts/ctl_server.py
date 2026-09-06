"""Start/stop control for the AI Provider Library helper (port 8091)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from helper_runtime import backend_root, is_running, start_app, stop_process

UNIT = "ai-provider-library-backend.service"
HOST = os.environ.get("APL_CTL_HOST", "0.0.0.0")
PORT = int(os.environ.get("APL_CTL_PORT", "8091"))
APP_HOST = os.environ.get("APL_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APL_PORT", "8090"))
CACHE_DIR = Path(os.environ.get("APL_CACHE", str(backend_root() / "cache")))


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args, UNIT],
        capture_output=True,
        text=True,
        check=False,
    )


def ctl_backend() -> str:
    mode = os.environ.get("APL_CTL_BACKEND", "auto").strip().lower()
    if mode in {"child", "systemd"}:
        return mode
    unit = Path.home() / ".config/systemd/user" / UNIT
    if shutil.which("systemctl") and unit.is_file():
        return "systemd"
    return "child"


def _running() -> bool:
    if ctl_backend() == "systemd":
        return _systemctl("is-active").stdout.strip() == "active"
    return is_running(CACHE_DIR)


def _start() -> bool:
    if ctl_backend() == "systemd":
        return _systemctl("start").returncode == 0
    start_app(backend_root(), APP_HOST, APP_PORT, CACHE_DIR)
    return is_running(CACHE_DIR)


def _stop() -> bool:
    if ctl_backend() == "systemd":
        return _systemctl("stop").returncode == 0
    return stop_process(CACHE_DIR)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _fmt: str, *_args: object) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/status":
            self._send(404, {"ok": False, "error": "not found"})
            return
        self._send(200, {"ok": True, "running": _running(), "backend": ctl_backend()})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        client = self.client_address[0] if self.client_address else "?"
        if path == "/start":
            if _running():
                print(f"ctl start noop from {client}", flush=True)
                self._send(200, {"ok": True, "running": True})
                return
            print(f"ctl start from {client}", flush=True)
            ok = _start()
            self._send(200 if ok else 500, {"ok": ok, "running": _running() if ok else False})
            return
        if path == "/stop":
            if not _running():
                print(f"ctl stop noop from {client}", flush=True)
                self._send(200, {"ok": True, "running": False})
                return
            print(f"ctl stop from {client}", flush=True)
            ok = _stop()
            self._send(200 if ok else 500, {"ok": ok, "running": False})
            return
        self._send(404, {"ok": False, "error": "not found"})


if __name__ == "__main__":
    HTTPServer((HOST, PORT), Handler).serve_forever()
