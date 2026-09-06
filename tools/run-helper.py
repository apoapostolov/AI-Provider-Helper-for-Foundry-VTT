#!/usr/bin/env python3
"""Run the AI Provider Library helper on this computer. Not on a Foundry hoster."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from http.server import HTTPServer
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent / "backend"
SCRIPTS = ROOT / "scripts"
HOSTED_ORIGINS = (
    "https://*.forge-vtt.com",
    "https://*.moltenhosting.com",
    "https://*.foundryserver.com",
)


def _die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    posix = ROOT / ".venv" / "bin" / "python3"
    if posix.is_file():
        return posix
    return ROOT / ".venv" / "bin" / "python"


def _bootstrap() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    venv_py = _venv_python()
    if not venv_py.is_file():
        uv = shutil.which("uv")
        if uv:
            subprocess.run([uv, "venv"], cwd=ROOT, check=True)
            subprocess.run([uv, "pip", "install", "-r", "requirements.txt"], cwd=ROOT, check=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
            venv_py = _venv_python()
            pip = [str(venv_py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
            subprocess.run(pip, cwd=ROOT, check=True)
        venv_py = _venv_python()
    probe = subprocess.run(
        [str(venv_py), "-c", "import fastapi, uvicorn"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pip = [str(venv_py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
        subprocess.run(pip, cwd=ROOT, check=True)
    return venv_py


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the AI Provider Library helper (8090 app, 8091 control)."
    )
    parser.add_argument("--host", default=os.environ.get("APL_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("APL_PORT", "8090")))
    parser.add_argument("--ctl-port", type=int, default=int(os.environ.get("APL_CTL_PORT", "8091")))
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="Extra Foundry origin pattern, for example https://*.forge-vtt.com",
    )
    parser.add_argument(
        "--foundry-hosted",
        action="store_true",
        help="Helper on this PC for a hosted Foundry world. Binds loopback and allows Forge/Molten origins.",
    )
    return parser.parse_args()


def main() -> None:
    if not (ROOT / "app" / "main.py").is_file():
        _die(
            "backend missing at "
            + str(ROOT)
            + ". Run this from the GitHub checkout, where tools/ and backend/ are siblings. See tools/HELPER.md."
        )
    args = _parse()
    host = "127.0.0.1" if args.foundry_hosted else args.host
    origins = list(args.allow_origin)
    if args.foundry_hosted:
        origins.extend(HOSTED_ORIGINS)
    os.environ["APL_HOST"] = host
    os.environ["APL_PORT"] = str(args.port)
    os.environ["APL_CTL_HOST"] = host
    os.environ["APL_CTL_PORT"] = str(args.ctl_port)
    os.environ["APL_CTL_BACKEND"] = "child"
    os.environ["APL_CACHE"] = str(ROOT / "cache")
    if origins:
        os.environ["APL_CORS_ORIGINS"] = ",".join(origins)
    _bootstrap()
    sys.path.insert(0, str(SCRIPTS))
    from ctl_server import Handler
    from helper_runtime import is_running, start_app, stop_process

    cache = Path(os.environ["APL_CACHE"])
    start_app(ROOT, host, args.port, cache)
    httpd = HTTPServer((host, args.ctl_port), Handler)
    shown = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    print("AI Provider Library helper")
    print(f"  app  http://{shown}:{args.port}/health")
    print(f"  ctl  http://{shown}:{args.ctl_port}/status")
    if args.foundry_hosted:
        print("  hosted Foundry: keep Endpoint Host at 127.0.0.1")
        print("  this script stays on YOUR PC. The hoster cannot run it.")
    print("  leave this window open")
    print(flush=True)
    if not is_running(cache):
        _die("helper app did not start. see backend/cache/helper.log")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopping helper", flush=True)
    finally:
        httpd.server_close()
        stop_process(cache)


if __name__ == "__main__":
    main()
