"""M6.2 candidate-ID-only preparation and single-token recycle endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.cleanup.diagnostics import InvalidDiagnosticsRequest, eligibility_diagnostics
from app.cleanup.service import CleanupError, cleanup_service
from app.intelligence.store import CandidateNotFound, InvalidCandidateScope
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


class CreateProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrepareProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_action: str = "recycle"


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, CleanupError):
        return HTTPException(status_code=exc.status_code, detail=exc.code)
    if isinstance(exc, InvalidDiagnosticsRequest):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, InvalidCandidateScope):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, CandidateNotFound):
        return HTTPException(status_code=404, detail="CANDIDATE_OR_RUN_NOT_FOUND")
    return HTTPException(status_code=503, detail="SNAPSHOT_DATABASE_UNAVAILABLE")


@router.get("/eligibility/summary")
def eligibility_summary(scope: str = "current_user_temp") -> dict[str, object]:
    try:
        return eligibility_diagnostics.summary(scope)
    except (InvalidDiagnosticsRequest, InvalidCandidateScope, CandidateNotFound,
            SnapshotStoreError) as exc:
        raise _error(exc) from exc


@router.get("/eligibility/candidates")
def eligibility_candidates(
    scope: str = "current_user_temp",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    filter: str = "all",
    sort: str = "size_desc",
) -> dict[str, object]:
    try:
        return eligibility_diagnostics.list(scope, limit, offset, filter, sort)
    except (InvalidDiagnosticsRequest, InvalidCandidateScope, CandidateNotFound,
            SnapshotStoreError) as exc:
        raise _error(exc) from exc


@router.get("/eligibility/candidates/{candidate_id}")
def eligibility_candidate_detail(
    candidate_id: str, scope: str = "current_user_temp",
) -> dict[str, object]:
    try:
        return eligibility_diagnostics.detail(candidate_id, scope)
    except (InvalidDiagnosticsRequest, InvalidCandidateScope, CandidateNotFound,
            SnapshotStoreError) as exc:
        raise _error(exc) from exc


@router.post("/prepare", dependencies=[Depends(require_local_origin)])
def prepare(body: PrepareRequest) -> dict[str, object]:
    try:
        return cleanup_service.prepare(body.candidate_id, body.requested_action)
    except (CleanupError, SnapshotStoreError) as exc:
        raise _error(exc) from exc


@router.post("/probes", dependencies=[Depends(require_local_origin)])
def create_probe(body: CreateProbeRequest) -> dict[str, object]:
    try:
        return cleanup_service.create_probe()
    except (CleanupError, SnapshotStoreError) as exc:
        raise _error(exc) from exc


@router.get("/probes")
def list_probes() -> dict[str, object]:
    try:
        return {"items": cleanup_service.list_probes()}
    except (CleanupError, SnapshotStoreError) as exc:
        raise _error(exc) from exc


@router.post("/probes/{probe_id}/prepare", dependencies=[Depends(require_local_origin)])
def prepare_probe(probe_id: str, body: PrepareProbeRequest) -> dict[str, object]:
    try:
        return cleanup_service.prepare_probe(probe_id, body.requested_action)
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
