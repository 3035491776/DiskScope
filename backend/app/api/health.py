from fastapi import APIRouter

from app.core.config import APP_MODE, APP_NAME, APP_VERSION


router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "mode": APP_MODE,
        "capabilities": {
            "scan": "read_only",
            "cleanup": "guarded_recycle",
            "cleanup_scope": "current_user_localappdata_temp_single_file",
        },
    }
