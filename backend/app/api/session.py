from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.security.session import local_session, require_local_origin, require_session


router = APIRouter(prefix="/api/v1/session", tags=["session"])


class BootstrapRequest(BaseModel):
    token: str = Field(min_length=1)


@router.post("/bootstrap", status_code=204, dependencies=[Depends(require_local_origin)])
def bootstrap_session(body: BootstrapRequest, response: Response) -> None:
    local_session.exchange(body.token, response)


@router.get("", dependencies=[Depends(require_session)])
def session_status() -> dict[str, bool]:
    return {"ready": True}
