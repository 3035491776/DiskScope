from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.scanner.path_guard import InvalidScanRoot
from app.scanner.whole_volume_gate import WholeVolumeScanDenied
from app.security.session import require_local_origin, require_session
from app.tasks.manager import (
    ResultNotReady,
    ScanAlreadyRunning,
    ScanNotFound,
    scan_tasks,
)


router = APIRouter(prefix="/api/v1/scans", tags=["scans"])


class CreateScanRequest(BaseModel):
    root: str = Field(min_length=1, max_length=1024)


def _api_error(error: Exception) -> HTTPException:
    if isinstance(error, WholeVolumeScanDenied):
        return HTTPException(status_code=403, detail=error.code)
    if isinstance(error, InvalidScanRoot):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, ScanAlreadyRunning) or isinstance(error, ResultNotReady):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ScanNotFound):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=500, detail="Scan request failed.")


@router.post("", status_code=202, dependencies=[Depends(require_session), Depends(require_local_origin)])
def create_scan(body: CreateScanRequest) -> dict[str, object]:
    try:
        return scan_tasks.create(body.root)
    except (InvalidScanRoot, WholeVolumeScanDenied, ScanAlreadyRunning) as exc:
        raise _api_error(exc) from exc


@router.get("/{scan_id}", dependencies=[Depends(require_session)])
def get_scan(scan_id: str) -> dict[str, object]:
    try:
        return scan_tasks.status(scan_id)
    except ScanNotFound as exc:
        raise _api_error(exc) from exc


@router.post(
    "/{scan_id}/cancel",
    dependencies=[Depends(require_session), Depends(require_local_origin)],
)
def cancel_scan(scan_id: str) -> dict[str, object]:
    try:
        return scan_tasks.cancel(scan_id)
    except ScanNotFound as exc:
        raise _api_error(exc) from exc


@router.get("/{scan_id}/top", dependencies=[Depends(require_session)])
def top_files(
    scan_id: str,
    kind: Literal["file"] = "file",
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, object]:
    try:
        files = scan_tasks.result(scan_id).top_files
        return {
            "scan_id": scan_id,
            "kind": kind,
            "total": len(files),
            "items": [asdict(file) for file in files[:limit]],
        }
    except (ScanNotFound, ResultNotReady) as exc:
        raise _api_error(exc) from exc


@router.get("/{scan_id}/directories", dependencies=[Depends(require_session)])
def directories(
    scan_id: str,
    parent_id: str = "",
) -> dict[str, object]:
    try:
        directory_map = scan_tasks.result(scan_id).directories
        if not directory_map and parent_id == "":
            return {"scan_id": scan_id, "parent_id": parent_id, "items": []}
        if parent_id not in directory_map:
            raise HTTPException(status_code=404, detail="Directory not found.")
        items = sorted(
            (directory for directory in directory_map.values() if directory.parent == parent_id),
            key=lambda directory: (-directory.subtree_bytes, directory.relative_path),
        )
        return {
            "scan_id": scan_id,
            "parent_id": parent_id,
            "items": [asdict(directory) for directory in items],
        }
    except (ScanNotFound, ResultNotReady) as exc:
        raise _api_error(exc) from exc
