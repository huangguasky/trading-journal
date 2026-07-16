"""Build and name the Python engine for Tauri's externalBin convention."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINARIES = ROOT / "desktop" / "src-tauri" / "binaries"
DIST = ROOT / "build" / "sidecar-dist"
WORK = ROOT / "build" / "sidecar-work"


def command_output(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def main() -> None:
    target = command_output("rustc", "--print", "host-tuple")
    executable_name = "engine-sidecar.exe" if sys.platform == "win32" else "engine-sidecar"
    target_name = f"engine-sidecar-{target}{'.exe' if sys.platform == 'win32' else ''}"

    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    BINARIES.mkdir(parents=True, exist_ok=True)
    for old_binary in BINARIES.glob("engine-sidecar-*"):
        old_binary.unlink()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "engine-sidecar",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
            "--specpath",
            str(WORK),
            "--collect-data",
            "engine",
            str(ROOT / "packaging" / "engine_sidecar.py"),
        ],
        cwd=ROOT,
        env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(WORK / "cache")},
        check=True,
    )
    source = DIST / executable_name
    destination = BINARIES / target_name
    shutil.copy2(source, destination)
    destination.chmod(destination.stat().st_mode | 0o111)
    print(destination)


if __name__ == "__main__":
    main()
