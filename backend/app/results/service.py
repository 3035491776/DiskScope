"""Resolve one browsable result per fixed scope without treating snapshots as live scans."""

from __future__ import annotations

from dataclasses import asdict

from app.scanner.c_drive import classify_system_item
from app.snapshots.store import SnapshotNotFound, SnapshotStore, SnapshotStoreError, snapshot_store
from app.tasks.manager import ResultNotReady, ScanNotFound, ScanTaskManager, scan_tasks


ALLOWED_SCOPES = frozenset({"fixture_sample", "project_workspace", "system_drive_c", "current_user_temp"})


class InvalidResultScope(ValueError):
    pass


def validate_scope(scope_key: str) -> None:
    if scope_key not in ALLOWED_SCOPES:
        raise InvalidResultScope("INVALID_RESULT_SCOPE")


class ResultResolver:
    def __init__(self, tasks: ScanTaskManager = scan_tasks,
                 snapshots: SnapshotStore = snapshot_store) -> None:
        self.tasks = tasks
        self.snapshots = snapshots

    def latest(self, scope_key: str) -> dict[str, object]:
        validate_scope(scope_key)
        live = self.tasks.latest_completed_status(scope_key)
        if live:
            return {
                "scope_key": scope_key, "source_type": "live", "result_id": live["scan_id"],
                "snapshot_id": live["snapshot_id"], "completed_at": live["finished_at"],
                "coverage": live["coverage"], "storage_status": "ready",
                "summary": {
                    "total_bytes": live["logical_bytes"], "file_count": live["files_seen"],
                    "directory_count": live["dirs_seen"], "duration_seconds": live["elapsed_ms"] / 1000,
                    "error_count": live["errors_count"], "skipped_count": live["skipped_count"],
                    "file_persistence_mode": live["file_persistence_mode"],
                    "file_persistence_limit": live["file_persistence_limit"],
                    "persisted_file_count": live["persisted_file_count"],
                    "observed_file_count": live["observed_file_count"],
                    "file_metadata_coverage": live["file_metadata_coverage"],
                },
            }
        try:
            rows = self.snapshots.list(scope_key, 1)
        except SnapshotStoreError:
            return self._empty(scope_key, "unavailable")
        if not rows:
            return self._empty(scope_key, "ready")
        item = rows[0]
        return {
            "scope_key": scope_key, "source_type": "snapshot", "result_id": item["snapshot_id"],
            "snapshot_id": item["snapshot_id"], "completed_at": item["completed_at"],
            "coverage": item["coverage"], "storage_status": "ready",
            "summary": {
                "total_bytes": item["total_bytes"], "file_count": item["file_count"],
                "directory_count": item["directory_count"],
                "duration_seconds": item["duration_seconds"],
                "error_count": item["error_count"], "skipped_count": item["skipped_count"],
                "file_persistence_mode": item["file_persistence_mode"],
                "file_persistence_limit": item["file_persistence_limit"],
                "persisted_file_count": item["persisted_file_count"],
                "observed_file_count": item["observed_file_count"],
                "file_metadata_coverage": (
                    "complete" if item["persisted_file_count"] == item["observed_file_count"]
                    else "limited"
                ),
            },
        }

    @staticmethod
    def _empty(scope_key: str, storage_status: str) -> dict[str, object]:
        return {"scope_key": scope_key, "source_type": "none", "result_id": None,
                "snapshot_id": None, "completed_at": None, "coverage": None,
                "storage_status": storage_status, "summary": None}

    def _source(self, scope_key: str, source_type: str, result_id: str):
        validate_scope(scope_key)
        if source_type == "live":
            status = self.tasks.status(result_id)
            if status["scope_key"] != scope_key or status["state"] != "completed":
                raise SnapshotNotFound(result_id)
            return self.tasks.result(result_id)
        if source_type == "snapshot":
            snapshot = self.snapshots.get(result_id)
            if snapshot["scope_key"] != scope_key:
                raise SnapshotNotFound(result_id)
            return None
        raise SnapshotNotFound(result_id)

    def directories(self, scope_key: str, source_type: str, result_id: str,
                    parent: str) -> list[dict[str, object]]:
        result = self._source(scope_key, source_type, result_id)
        if result is None:
            rows = self.snapshots.directories(result_id, parent)
            return [self._snapshot_directory(row, scope_key) for row in rows]
        if parent not in result.directories:
            raise SnapshotNotFound(parent)
        rows = sorted((directory for directory in result.directories.values()
                       if directory.parent == parent),
                      key=lambda item: (-item.subtree_bytes, item.relative_path))
        return [self._live_directory(row, result, scope_key) for row in rows]

    def top(self, scope_key: str, source_type: str, result_id: str,
            kind: str, limit: int) -> tuple[list[dict[str, object]], int | None]:
        result = self._source(scope_key, source_type, result_id)
        if result is None:
            if kind == "file":
                rows = self.snapshots.top_files(result_id, limit)
                return [self._snapshot_file(row, scope_key) for row in rows], None
            rows = self.snapshots.top_directories(result_id, limit)
            return [self._snapshot_directory(row, scope_key) for row in rows], None
        if kind == "file":
            return [self._live_file(row, scope_key) for row in result.top_files[:limit]], len(result.top_files)
        rows = sorted((directory for path, directory in result.directories.items() if path),
                      key=lambda item: (-item.subtree_bytes, item.relative_path))
        return [self._live_directory(row, result, scope_key) for row in rows[:limit]], len(rows)

    @staticmethod
    def _live_file(row, scope_key: str) -> dict[str, object]:
        return {**asdict(row), **(classify_system_item(row.relative_path)
                                 if scope_key == "system_drive_c" else {})}

    @staticmethod
    def _snapshot_file(row: dict[str, object], scope_key: str) -> dict[str, object]:
        path = str(row["relative_path"])
        return {**row, "parent": path.rpartition("/")[0], "attributes": None,
                **(classify_system_item(path) if scope_key == "system_drive_c" else {})}

    @staticmethod
    def _live_directory(row, result, scope_key: str) -> dict[str, object]:
        path = row.relative_path
        return {**asdict(row), "node_id": path, "name": path.rsplit("/", 1)[-1],
                "coverage": "limited" if result.cancelled or path in result.limited_directories else "complete",
                **(classify_system_item(path) if scope_key == "system_drive_c" else {})}

    @staticmethod
    def _snapshot_directory(row: dict[str, object], scope_key: str) -> dict[str, object]:
        path = str(row["relative_path"])
        return {"node_id": path, "relative_path": path, "name": row["name"],
                "parent": row["parent_relative_path"], "direct_bytes": row["direct_bytes"],
                "subtree_bytes": row["subtree_bytes"], "direct_file_count": None,
                "file_count": row["file_count"], "children_count": row["directory_count"],
                "coverage": row["coverage"],
                **(classify_system_item(path) if scope_key == "system_drive_c" else {})}


result_resolver = ResultResolver()
