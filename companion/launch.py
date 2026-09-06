#!/usr/bin/env python3
"""Companion entry: loopback helper on this PC. No GitHub checkout required."""

from __future__ import annotations

import argparse
import os
import sys
from http.server import HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOSTED_ORIGINS = (
    "https://*.forge-vtt.com",
    "https://*.moltenhosting.com",
    "https://*.foundryserver.com",
)


def _die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def backend_dir() -> Path:
    packed = HERE / "backend"
    if (packed / "app" / "main.py").is_file():
        return packed
    repo = HERE.parent / "backend"
    if (repo / "app" / "main.py").is_file():
        return repo
    _die("backend missing. Download AI-Helper-windows.zip from GitHub Releases.")
    raise AssertionError


def default_cache() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "AI-Provider-Library"
    return Path.home() / ".cache" / "ai-provider-library"


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Helper companion (8090 app, 8091 control).")
    parser.add_argument("--hosted", "--foundry-hosted", action="store_true")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APL_PORT", "8090")))
    parser.add_argument("--ctl-port", type=int, default=int(os.environ.get("APL_CTL_PORT", "8091")))
    return parser.parse_args()


def main() -> None:
    args = _parse()
    root = backend_dir()
    host = "127.0.0.1"
    cache = default_cache()
    os.environ["APL_HOST"] = host
    os.environ["APL_PORT"] = str(args.port)
    os.environ["APL_CTL_HOST"] = host
    os.environ["APL_CTL_PORT"] = str(args.ctl_port)
    os.environ["APL_CTL_BACKEND"] = "child"
    os.environ["APL_CACHE"] = str(cache)
    if args.hosted:
        os.environ["APL_CORS_ORIGINS"] = ",".join(HOSTED_ORIGINS)
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    from ctl_server import Handler
    from helper_runtime import is_running, start_app, stop_process

    start_app(root, host, args.port, cache)
    httpd = HTTPServer((host, args.ctl_port), Handler)
    print("AI Helper")
    print(f"  app  http://{host}:{args.port}/health")
    print(f"  ctl  http://{host}:{args.ctl_port}/status")
    print(f"  vault {cache}")
    if args.hosted:
        print("  hosted Foundry: keep Endpoint Host at 127.0.0.1")
    print("  leave this window open")
    print(flush=True)
    if not is_running(cache):
        _die("helper app did not start. see helper.log in the vault folder.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopping helper", flush=True)
    finally:
        httpd.server_close()
        stop_process(cache)


if __name__ == "__main__":
    main()
