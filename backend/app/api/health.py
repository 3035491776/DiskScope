from fastapi import APIRouter

from app.core.config import APP_MODE, APP_NAME, APP_VERSION, DEVELOPER_MODE


router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "mode": APP_MODE,
        "developer_mode": DEVELOPER_MODE,
        "capabilities": {
            "scan": "read_only",
            "cleanup": "guarded_recycle",
            "cleanup_scope": "bounded_candidate_batch_and_manual_review",
            "cleanup_batch_limit": 200,
        },
    }
