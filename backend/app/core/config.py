import os
import sys
from pathlib import Path


APP_NAME = "DiskScope"
APP_VERSION = "0.2.0"
APP_MODE = "guarded_cleanup"
HOST = "127.0.0.1"
PORT = 8765
PACKAGED_RELEASE = bool(getattr(sys, "frozen", False))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)).resolve()
RUNTIME_ROOT = Path(sys.executable).resolve().parent if PACKAGED_RELEASE else PROJECT_ROOT
FRONTEND_DIST = RESOURCE_ROOT / "frontend" / "dist"
DATA_DIR = RUNTIME_ROOT / "data"
LOG_DIR = RUNTIME_ROOT / "logs"
DEVELOPER_MODE = not PACKAGED_RELEASE and os.environ.get("DISKSCOPE_DEV_MODE") == "1"
