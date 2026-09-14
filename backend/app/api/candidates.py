"""Session-protected recommendations from completed SQLite snapshots only."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.intelligence.store import (
    CandidateNotFound, InvalidCandidateScope, candidate_store,
)
from app.security.session import require_local_origin, require_session
from app.snapshots.store import SnapshotNotFound, SnapshotStoreError


router = APIRouter(prefix="/api/v1", tags=["candidates"], dependencies=[Depends(require_session)])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, SnapshotStoreError):
        return HTTPException(status_code=503, detail=exc.code)
    if isinstance(exc, InvalidCandidateScope):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=404, detail="CANDIDATE_OR_SNAPSHOT_NOT_FOUND")


@router.get("/candidates")
def list_candidates(
    scope_key: str = "system_drive_c", category: str | None = None,
    risk: str | None = None, confidence: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, object]:
    try:
        return candidate_store.list_latest(scope_key, category, risk, confidence, limit)
    except (SnapshotStoreError, InvalidCandidateScope) as exc:
        raise _error(exc) from exc


@router.get("/candidates/{candidate_id}")
def candidate_detail(candidate_id: str, scope_key: str = "system_drive_c") -> dict[str, object]:
    try:
        return candidate_store.detail(candidate_id, scope_key)
    except (SnapshotStoreError, InvalidCandidateScope, CandidateNotFound) as exc:
        raise _error(exc) from exc


@router.get("/candidate-runs")
def list_candidate_runs(scope_key: str = "system_drive_c") -> dict[str, object]:
    try:
        return {"items": candidate_store.list_runs(scope_key)}
    except (SnapshotStoreError, InvalidCandidateScope) as exc:
        raise _error(exc) from exc


@router.post("/snapshots/{snapshot_id}/analyze", dependencies=[Depends(require_local_origin)])
def analyze_snapshot(snapshot_id: str) -> dict[str, object]:
    try:
        return candidate_store.analyze_snapshot(snapshot_id)
    except (SnapshotStoreError, SnapshotNotFound, InvalidCandidateScope) as exc:
        raise _error(exc) from exc
