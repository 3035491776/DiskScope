"""Session-protected recommendations from completed SQLite snapshots only."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.intelligence.store import (
    CandidateNotFound, InvalidCandidateScope, candidate_store,
)
from app.security.session import require_local_origin, require_session
from app.snapshots.store import SnapshotNotFound, SnapshotStoreError
from app.cleanup.policy import ExecutionPolicyEngine


router = APIRouter(prefix="/api/v1", tags=["candidates"], dependencies=[Depends(require_session)])


def _add_execution_policy(item: dict[str, object], scope_key: str) -> None:
    reasons = ExecutionPolicyEngine().static_reasons(item, scope_key)
    item["execution_hint"] = "suggestion_only" if reasons else "prepare_available"
    item["execution_policy"] = {
        "eligibility": "ineligible" if reasons else "eligible_for_review",
        "allowed_actions": [] if reasons else ["dry_run"],
        "block_reasons": reasons,
        "required_checks": ["path_scope", "parent_reparse", "target_type", "size", "mtime", "age"],
        "real_execution_enabled": False,
    }


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
        listing = candidate_store.list_latest(scope_key, category, risk, confidence, limit)
        for item in listing["items"]:
            _add_execution_policy(item, scope_key)
        return listing
    except (SnapshotStoreError, InvalidCandidateScope) as exc:
        raise _error(exc) from exc


@router.get("/candidates/{candidate_id}")
def candidate_detail(candidate_id: str, scope_key: str = "system_drive_c") -> dict[str, object]:
    try:
        detail = candidate_store.detail(candidate_id, scope_key)
        _add_execution_policy(detail["candidate"], scope_key)
        return detail
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
