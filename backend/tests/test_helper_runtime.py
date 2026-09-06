from __future__ import annotations

import sys
import time
from pathlib import Path

from helper_runtime import is_running, start_process, stop_process


def test_start_stop_child(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    pid = start_process(argv, tmp_path, tmp_path)
    assert pid > 0
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not is_running(tmp_path):
        time.sleep(0.05)
    assert is_running(tmp_path)
    assert stop_process(tmp_path)
    assert not is_running(tmp_path)
