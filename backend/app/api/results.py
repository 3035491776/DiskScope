"""Session-protected, read-only browsing of current or saved scan metadata."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.results.service import InvalidResultScope, result_resolver
from app.security.session import require_session
from app.snapshots.store import SnapshotNotFound, SnapshotStoreError
from app.tasks.manager import ResultNotReady, ScanNotFound


router = APIRouter(prefix="/api/v1/results", tags=["results"], dependencies=[Depends(require_session)])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidResultScope):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, SnapshotStoreError):
        return HTTPException(status_code=503, detail=exc.code)
    return HTTPException(status_code=404, detail="RESULT_NOT_FOUND")


@router.get("/latest")
def latest(scope_key: str) -> dict[str, object]:
    try:
        return result_resolver.latest(scope_key)
    except InvalidResultScope as exc:
        raise _error(exc) from exc


@router.get("/{source_type}/{result_id}/directories")
def directories(source_type: Literal["live", "snapshot"], result_id: str,
                scope_key: str, parent_id: str = "") -> dict[str, object]:
    try:
        items = result_resolver.directories(scope_key, source_type, result_id, parent_id)
        return {"source_type": source_type, "result_id": result_id, "parent_id": parent_id, "items": items}
    except (InvalidResultScope, SnapshotStoreError, SnapshotNotFound, ScanNotFound, ResultNotReady) as exc:
        raise _error(exc) from exc


@router.get("/{source_type}/{result_id}/top")
def top(source_type: Literal["live", "snapshot"], result_id: str, scope_key: str,
        kind: Literal["file", "directory"] = "file",
        limit: int = Query(100, ge=1, le=1000)) -> dict[str, object]:
    try:
        items, total = result_resolver.top(scope_key, source_type, result_id, kind, limit)
        return {"source_type": source_type, "result_id": result_id, "kind": kind,
                "total": total, "items": items}
    except (InvalidResultScope, SnapshotStoreError, SnapshotNotFound, ScanNotFound, ResultNotReady) as exc:
        raise _error(exc) from exc
