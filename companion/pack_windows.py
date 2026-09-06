#!/usr/bin/env python3
"""Build AI-Helper-windows.zip. Not module.zip. Do not run foundry-zip on this."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

COMPANION = Path(__file__).resolve().parent
REPO = COMPANION.parent
PYTHON_VERSION = "3.12.10"
EMBED_NAME = f"python-{PYTHON_VERSION}-embed-amd64.zip"
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{EMBED_NAME}"
RUNTIME_PACKAGES = ("fastapi", "uvicorn", "httpx", "pydantic", "cryptography")
LAUNCHERS = (
    "AI Helper.bat",
    "AI Helper.ps1",
    "AI Helper (hosted).bat",
    "launch.py",
    "README.md",
)
SKIP_BACKEND_DIR_NAMES = {
    ".venv",
    "__pycache__",
    "tests",
    "cache",
    ".pytest_cache",
}


def runtime_packages() -> tuple[str, ...]:
    return RUNTIME_PACKAGES


def _ignore_backend(_directory: str, names: list[str]) -> list[str]:
    skipped = []
    for name in names:
        if name in SKIP_BACKEND_DIR_NAMES or name.endswith(".pyc"):
            skipped.append(name)
    return skipped


def stage_layout(dest: Path, repo: Path = REPO) -> Path:
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    companion = repo / "companion"
    for name in LAUNCHERS:
        src = companion / name
        if not src.is_file():
            raise FileNotFoundError(src)
        shutil.copy2(src, dest / name)
    backend_src = repo / "backend"
    backend_dst = dest / "backend"
    shutil.copytree(
        backend_src / "app",
        backend_dst / "app",
        ignore=_ignore_backend,
    )
    shutil.copytree(
        backend_src / "scripts",
        backend_dst / "scripts",
        ignore=_ignore_backend,
    )
    (backend_dst / "requirements-runtime.txt").write_text(
        "\n".join(RUNTIME_PACKAGES) + "\n",
        encoding="utf-8",
    )
    return dest


def enable_embed_site(python_dir: Path) -> Path:
    matches = list(python_dir.glob("python*._pth"))
    if not matches:
        raise FileNotFoundError(f"no python*._pth in {python_dir}")
    path = matches[0]
    text = path.read_text(encoding="utf-8")
    lines = [line.rstrip() for line in text.splitlines()]
    wanted = "Lib\\site-packages"
    if wanted not in lines and "Lib/site-packages" not in lines:
        lines.append(wanted)
    out = []
    seen_site = False
    for line in lines:
        stripped = line.lstrip("#").strip()
        if stripped == "import site":
            out.append("import site")
            seen_site = True
        else:
            out.append(line)
    if not seen_site:
        out.append("import site")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    (python_dir / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    return path


def fetch_embed(python_dir: Path, url: str = EMBED_URL) -> None:
    python_dir.mkdir(parents=True, exist_ok=True)
    archive = python_dir.parent / EMBED_NAME
    urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(python_dir)
    archive.unlink(missing_ok=True)
    enable_embed_site(python_dir)


def install_win_wheels(site: Path, packages: tuple[str, ...] = RUNTIME_PACKAGES) -> None:
    site.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        str(site),
        "--platform",
        "win_amd64",
        "--python-version",
        "312",
        "--implementation",
        "cp",
        "--abi",
        "cp312",
        "--only-binary",
        ":all:",
        "--upgrade",
        *packages,
    ]
    subprocess.run(cmd, check=True)


def write_zip(stage: Path, zip_path: Path) -> Path:
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(stage)
            zf.write(path, Path("AI-Helper") / rel)
    return zip_path


def pack(*, layout_only: bool = False, skip_wheels: bool = False, dest: Path | None = None) -> Path:
    build = dest or (COMPANION / ".build" / "AI-Helper")
    stage_layout(build)
    if not layout_only:
        python_dir = build / "python"
        fetch_embed(python_dir)
        if not skip_wheels:
            install_win_wheels(python_dir / "Lib" / "site-packages")
    zip_path = COMPANION / "dist" / "AI-Helper-windows.zip"
    return write_zip(build, zip_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack the Windows AI Helper zip.")
    parser.add_argument("--layout-only", action="store_true", help="Skip CPython download and wheels.")
    parser.add_argument("--skip-wheels", action="store_true")
    parser.add_argument("--dest", type=Path, default=None)
    args = parser.parse_args()
    path = pack(layout_only=args.layout_only, skip_wheels=args.skip_wheels, dest=args.dest)
    print(path)


if __name__ == "__main__":
    main()
