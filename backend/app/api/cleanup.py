"""Candidate-ID-only cleanup preflight and audited, disabled execution endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.cleanup.service import CleanupError, cleanup_service
from app.security.session import require_local_origin, require_session
from app.snapshots.store import SnapshotStoreError

router = APIRouter(prefix="/api/v1/cleanup", tags=["cleanup"],
                   dependencies=[Depends(require_session)])


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=256)
    requested_action: str = "recycle"


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_token: str = Field(min_length=1, max_length=256)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, CleanupError):
        return HTTPException(status_code=exc.status_code, detail=exc.code)
    return HTTPException(status_code=503, detail="SNAPSHOT_DATABASE_UNAVAILABLE")


@router.post("/prepare", dependencies=[Depends(require_local_origin)])
def prepare(body: PrepareRequest) -> dict[str, object]:
    try:
        return cleanup_service.prepare(body.candidate_id, body.requested_action)
    except (CleanupError, SnapshotStoreError) as exc:
        raise _error(exc) from exc


@router.post("/execute", dependencies=[Depends(require_local_origin)])
def execute(body: ExecuteRequest) -> dict[str, object]:
    try:
        return cleanup_service.execute(body.execution_token)
    except (CleanupError, SnapshotStoreError) as exc:
        raise _error(exc) from exc


@router.get("/executions")
def executions(limit: int = Query(50, ge=1, le=100)) -> dict[str, object]:
    try:
        return {"items": cleanup_service.list(limit)}
    except SnapshotStoreError as exc:
        raise _error(exc) from exc


@router.get("/executions/{execution_id}")
def execution_detail(execution_id: str) -> dict[str, object]:
    try:
        return cleanup_service.detail(execution_id)
    except (CleanupError, SnapshotStoreError) as exc:
        raise _error(exc) from exc
