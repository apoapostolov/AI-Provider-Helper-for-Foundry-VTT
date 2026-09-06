"""Start and stop the 8090 helper as a child process. No systemd."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PID_NAME = "helper.pid"
LOG_NAME = "helper.log"


def backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    posix = root / ".venv" / "bin" / "python3"
    if posix.is_file():
        return posix
    return root / ".venv" / "bin" / "python"


def pid_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / PID_NAME


def log_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / LOG_NAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x00100000, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_pid(cache_dir: Path) -> int | None:
    path = pid_path(cache_dir)
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if not _pid_alive(pid):
        path.unlink(missing_ok=True)
        return None
    return pid


def is_running(cache_dir: Path) -> bool:
    return read_pid(cache_dir) is not None


def uvicorn_argv(root: Path, host: str, port: int) -> list[str]:
    python = venv_python(root)
    exe = str(python) if python.is_file() else sys.executable
    return [
        exe,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
        "--timeout-graceful-shutdown",
        "3",
    ]


def start_process(argv: list[str], cache_dir: Path, cwd: Path) -> int:
    existing = read_pid(cache_dir)
    if existing is not None:
        return existing
    cache_dir.mkdir(parents=True, exist_ok=True)
    log = log_path(cache_dir).open("ab")
    kwargs: dict = {
        "cwd": str(cwd),
        "stdout": log,
        "stderr": subprocess.STDOUT,
        "close_fds": os.name != "nt",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, **kwargs)
    pid_path(cache_dir).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def start_app(root: Path, host: str, port: int, cache_dir: Path) -> int:
    return start_process(uvicorn_argv(root, host, port), cache_dir, root)


def stop_process(cache_dir: Path, timeout: float = 8.0) -> bool:
    pid = read_pid(cache_dir)
    if pid is None:
        return True
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(0.1)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    pid_path(cache_dir).unlink(missing_ok=True)
    return not is_running(cache_dir)
