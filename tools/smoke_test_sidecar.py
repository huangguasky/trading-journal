"""Start the frozen engine and verify the desktop-facing HTTP contract."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "desktop" / "src-tauri" / "binaries" / "engine-sidecar-runtime"


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> None:
    executable = RUNTIME / ("engine-sidecar.exe" if os.name == "nt" else "engine-sidecar")
    if not executable.is_file():
        raise SystemExit(f"frozen engine is missing: {executable}")

    port = available_port()
    with tempfile.TemporaryDirectory(prefix="trading-journal-smoke-") as data_dir:
        env = {
            **os.environ,
            "TJ_DATA_DIR": data_dir,
            "TJ_PORT": str(port),
            "PYTHONUNBUFFERED": "1",
        }
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                [str(executable)],
                env=env,
                stdout=output,
                stderr=output,
                creationflags=creationflags,
            )
            try:
                verify_health(process, port, output)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


def verify_health(process: subprocess.Popen, port: int, output) -> None:
    deadline = time.monotonic() + 90
    url = f"http://127.0.0.1:{port}/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            output.seek(0)
            logs = output.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"frozen engine exited with code {exit_code}:\n{logs}")
        try:
            request = Request(url, headers={"Origin": "http://tauri.localhost"})
            with urlopen(request, timeout=1) as response:
                payload = json.load(response)
                assert payload["ok"] is True
                assert response.headers["X-Trading-Journal-Engine"] == "4"
                assert response.headers["Access-Control-Expose-Headers"] == "X-Trading-Journal-Engine"
                assert response.headers["Access-Control-Allow-Private-Network"] == "true"
                print(f"Frozen engine smoke test passed on {sys.platform}: {url}")
                return
        except (AssertionError, KeyError, OSError, URLError, ValueError) as error:
            last_error = error
            time.sleep(0.2)
    raise TimeoutError(f"frozen engine did not become healthy: {last_error}")


if __name__ == "__main__":
    main()
