"""Small, session-protected history views over the local snapshot database."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.security.session import require_session
from app.snapshots.store import (
    SnapshotNotFound, SnapshotScopeMismatch, SnapshotStoreError, snapshot_store,
)


router = APIRouter(prefix="/api/v1", tags=["snapshots"], dependencies=[Depends(require_session)])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, SnapshotStoreError):
        return HTTPException(status_code=503, detail=exc.code)
    if isinstance(exc, SnapshotScopeMismatch):
        return HTTPException(status_code=400, detail="SNAPSHOT_SCOPE_MISMATCH")
    return HTTPException(status_code=404, detail="SNAPSHOT_NOT_FOUND")


@router.get("/snapshots")
def list_snapshots(scope_key: str | None = None, limit: int = Query(20, ge=1, le=20)) -> dict[str, object]:
    try:
        items = snapshot_store.list(scope_key, limit)
        return {"items": items, "total": len(items)}
    except SnapshotStoreError as exc:
        raise _error(exc) from exc


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str) -> dict[str, object]:
    try:
        return snapshot_store.get(snapshot_id)
    except (SnapshotStoreError, SnapshotNotFound) as exc:
        raise _error(exc) from exc


@router.get("/snapshots/{snapshot_id}/directories")
def get_snapshot_directories(snapshot_id: str, parent: str = "") -> dict[str, object]:
    try:
        return {"snapshot_id": snapshot_id, "parent": parent, "items": snapshot_store.directories(snapshot_id, parent)}
    except (SnapshotStoreError, SnapshotNotFound) as exc:
        raise _error(exc) from exc


@router.get("/compare")
def compare(base: str, target: str) -> dict[str, object]:
    try:
        return snapshot_store.compare(base, target)
    except (SnapshotStoreError, SnapshotNotFound, SnapshotScopeMismatch) as exc:
        raise _error(exc) from exc
