"""Start the local service and open its verified web page."""

import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_BACKEND = SOURCE_ROOT / "backend"
if not getattr(sys, "frozen", False) and str(SOURCE_BACKEND) not in sys.path:
    sys.path.insert(0, str(SOURCE_BACKEND))

from app.core.config import (  # noqa: E402
    APP_VERSION, FRONTEND_DIST, HOST, LOG_DIR, PACKAGED_RELEASE, PORT, RUNTIME_ROOT,
)


ROOT = RUNTIME_ROOT
BACKEND = SOURCE_BACKEND
DIST = FRONTEND_DIST
LOGS = LOG_DIR
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
                if (response.status == 200 and payload.get("status") == "ok" and
                        payload.get("app") == "DiskScope" and
                        payload.get("version") == APP_VERSION and
                        payload.get("mode") == "guarded_cleanup" and
                        payload.get("capabilities", {}).get("scan") == "read_only" and
                        payload.get("capabilities", {}).get("cleanup") == "guarded_recycle"):
                    return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Backend did not pass GET /health within {timeout:g} seconds.")


def serve() -> int:
    """Internal packaged backend mode; never exposed as the user entry point."""
    import uvicorn
    from app.main import app

    config = uvicorn.Config(app, host=HOST, port=PORT, workers=1, access_log=False)
    server = uvicorn.Server(config)

    if os.environ.get("DISKSCOPE_PARENT_WATCH") == "1":
        def stop_with_parent() -> None:
            # The launcher owns the write end of this private pipe. EOF means
            # that it exited, including an abnormal termination.
            try:
                sys.stdin.buffer.read(1)
            except OSError:
                pass
            server.should_exit = True

        threading.Thread(
            target=stop_with_parent, name="diskscope-parent-watch", daemon=True,
        ).start()

    server.run()
    return 0


def backend_command() -> list[str]:
    if PACKAGED_RELEASE:
        return [sys.executable, "--serve"]
    return [
        sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(BACKEND),
        "--host", HOST, "--port", str(PORT), "--workers", "1", "--no-access-log",
    ]


def main() -> int:
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
    except OSError:
        print(
            f"Startup failed: The log directory is not writable: {LOGS}. "
            "Move the complete release to a user-writable folder and retry.",
            file=sys.stderr,
        )
        return 1

    logging.basicConfig(
        filename=LOGS / "launcher.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        if not DIST.joinpath("index.html").is_file():
            raise RuntimeError(
                "Web UI resources are missing. Re-extract the complete DiskScope release."
            )
        data_directory = ROOT / "data"
        try:
            data_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"The data directory is not writable: {data_directory}. "
                "Move the complete release to a user-writable folder and retry."
            ) from exc
        check_port_available()
    except (OSError, RuntimeError) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1

    command = backend_command()
    logging.info("Starting backend on %s:%s", HOST, PORT)
    launch_token = secrets.token_urlsafe(32)
    child_environment = os.environ.copy()
    child_environment["DISKSCOPE_BOOTSTRAP_TOKEN"] = launch_token
    child_environment["DISKSCOPE_PARENT_WATCH"] = "1"
    try:
        with (LOGS / "backend.log").open("a", encoding="utf-8") as backend_log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=backend_log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
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
                if process.stdin is not None:
                    process.stdin.close()
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
    raise SystemExit(serve() if "--serve" in sys.argv[1:] else main())
