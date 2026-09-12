from pathlib import Path


APP_NAME = "DiskScope"
APP_VERSION = "0.1.0"
APP_MODE = "read_only"
HOST = "127.0.0.1"
PORT = 8765
PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

