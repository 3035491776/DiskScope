from fastapi import APIRouter, Depends

from app.security.session import require_session
from app.system.volumes import list_fixed_volumes


router = APIRouter(prefix="/api/v1/volumes", tags=["volumes"])


@router.get("", dependencies=[Depends(require_session)])
def get_volumes() -> dict[str, object]:
    return {"items": list_fixed_volumes()}
