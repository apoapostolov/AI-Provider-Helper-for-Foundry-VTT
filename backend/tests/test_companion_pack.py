from __future__ import annotations

import sys
from pathlib import Path

COMPANION = Path(__file__).resolve().parents[2] / "companion"
if str(COMPANION) not in sys.path:
    sys.path.insert(0, str(COMPANION))

from pack_windows import enable_embed_site, runtime_packages, stage_layout  # noqa: E402


def test_runtime_packages_skip_pytest() -> None:
    names = runtime_packages()
    assert "fastapi" in names
    assert "pytest" not in names
    assert "pytest-asyncio" not in names


def test_stage_layout_is_loopback_companion(tmp_path: Path) -> None:
    dest = tmp_path / "AI-Helper"
    stage_layout(dest)
    assert (dest / "AI Helper.bat").is_file()
    assert (dest / "AI Helper.ps1").is_file()
    assert (dest / "AI Helper (hosted).bat").is_file()
    assert (dest / "launch.py").is_file()
    assert (dest / "backend" / "app" / "main.py").is_file()
    assert (dest / "backend" / "scripts" / "ctl_server.py").is_file()
    assert not (dest / "backend" / "tests").exists()
    assert not (dest / "python").exists()
    req = (dest / "backend" / "requirements-runtime.txt").read_text(encoding="utf-8")
    assert "fastapi" in req
    assert "pytest" not in req
    launch = (dest / "launch.py").read_text(encoding="utf-8")
    assert 'host = "127.0.0.1"' in launch
    assert "0.0.0.0" not in launch
    bat = (dest / "AI Helper.bat").read_text(encoding="utf-8")
    assert "AI Helper.ps1" in bat
    hosted = (dest / "AI Helper (hosted).bat").read_text(encoding="utf-8")
    assert "-Hosted" in hosted


def test_enable_embed_site_uncomments_import(tmp_path: Path) -> None:
    pth = tmp_path / "python312._pth"
    pth.write_text("python312.zip\n.\n# import site\n", encoding="utf-8")
    enable_embed_site(tmp_path)
    text = pth.read_text(encoding="utf-8")
    assert "import site" in text
    assert "# import site" not in text
    assert "Lib\\site-packages" in text
    assert (tmp_path / "Lib" / "site-packages").is_dir()
