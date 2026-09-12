"""Start the local service and open its verified web page."""

import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"
LOGS = ROOT / "logs"
HOST = "127.0.0.1"
PORT = 8765
BASE_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{BASE_URL}/health"


def check_port_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, PORT))
        except OSError as exc:
            raise RuntimeError(f"Local port {PORT} is already in use. Close the existing service and retry.") from exc


def wait_for_health(process: subprocess.Popen[bytes], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Backend exited before becoming healthy (exit code {process.returncode}).")
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=0.5) as response:
                payload = json.load(response)
                if response.status == 200 and payload == {
                    "status": "ok",
                    "app": "DiskScope",
                    "version": "0.1.0",
                    "mode": "read_only",
                }:
                    return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Backend did not pass GET /health within {timeout:g} seconds.")


def main() -> int:
    if not DIST.joinpath("index.html").is_file():
        print("Web UI is not built. Please run setup.bat first.", file=sys.stderr)
        return 1

    try:
        LOGS.mkdir(exist_ok=True)
        logging.basicConfig(
            filename=LOGS / "launcher.log",
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        check_port_available()
    except (OSError, RuntimeError) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1

    command = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--app-dir", str(BACKEND), "--host", HOST, "--port", str(PORT),
        "--workers", "1", "--no-access-log",
    ]
    logging.info("Starting backend on %s:%s", HOST, PORT)
    launch_token = secrets.token_urlsafe(32)
    child_environment = os.environ.copy()
    child_environment["DISKSCOPE_BOOTSTRAP_TOKEN"] = launch_token
    try:
        with (LOGS / "backend.log").open("a", encoding="utf-8") as backend_log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=backend_log,
                stderr=subprocess.STDOUT,
                env=child_environment,
            )
            try:
                wait_for_health(process)
                logging.info("Backend health check passed")
                print(f"DiskScope is ready: {BASE_URL}/")
                try:
                    browser_opened = webbrowser.open(
                        f"{BASE_URL}/#bootstrap={quote(launch_token)}"
                    )
                except (OSError, webbrowser.Error):
                    browser_opened = False
                if not browser_opened:
                    print(
                        "Open this one-time local address in your browser: "
                        f"{BASE_URL}/#bootstrap={quote(launch_token)}"
                    )
                return process.wait()
            except KeyboardInterrupt:
                print("Stopping DiskScope...")
                return 0
            except RuntimeError as exc:
                logging.error("Startup failed: %s", exc)
                print(f"Startup failed: {exc} See logs/backend.log.", file=sys.stderr)
                return 1
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    except OSError as exc:
        logging.error("Could not start backend: %s", exc)
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
