from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    cfg = Config(host="127.0.0.1", port=8090, cache_dir=tmp_path / "cache", debug=False)
    return TestClient(create_app(cfg))
