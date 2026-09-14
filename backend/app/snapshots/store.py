"""Versioned SQLite history of completed, already-collected scan metadata."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.core.config import PROJECT_ROOT
from app.scanner.models import ScanResult
from app.snapshots.compare import compare_directories, compare_top_files, delta_ratio


SCHEMA_VERSION = 1
RETENTION_PER_SCOPE = 20
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "diskscope.db"
SUMMARY_COLUMNS = ("id AS snapshot_id, scan_id, scope_key, scope_label, status, "
                   "started_at, completed_at, duration_seconds, total_bytes, file_count, "
                   "directory_count, error_count, skipped_count, coverage, created_at")


class SnapshotStoreError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SnapshotNotFound(LookupError):
    pass


class SnapshotScopeMismatch(ValueError):
    pass


def scope_for_root(root_label: str) -> tuple[str, str]:
    if root_label == "project_workspace":
        return "project_workspace", "Project Workspace"
    if root_label == "tests/fixtures/sample_disk":
        return "fixture_sample", "Fixture Sample"
    return f"fixture_path:{root_label}", root_label


class SnapshotStore:
    def __init__(self, database: Path = DEFAULT_DATABASE):
        self.database = Path(database)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = None
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database, timeout=2)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise SnapshotStoreError("SNAPSHOT_DATABASE_VERSION_UNSUPPORTED")
            if version == 0:
                self._initialize(connection)
            else:
                expected = {"scan_snapshots", "directory_snapshots", "file_snapshots"}
                actual = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )}
                if not expected <= actual:
                    raise SnapshotStoreError("SNAPSHOT_DATABASE_UNAVAILABLE")
            yield connection
        except sqlite3.Error as exc:
            raise SnapshotStoreError("SNAPSHOT_DATABASE_UNAVAILABLE") from exc
        except OSError as exc:
            raise SnapshotStoreError("SNAPSHOT_DATABASE_UNAVAILABLE") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            # A reader and the first writer may both observe version 0 before this lock.
            if connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
                connection.commit()
                return
            connection.execute("""CREATE TABLE scan_snapshots (
                id TEXT PRIMARY KEY, scan_id TEXT NOT NULL UNIQUE, scope_key TEXT NOT NULL,
                scope_label TEXT NOT NULL, root_path TEXT NOT NULL, status TEXT NOT NULL
                CHECK(status = 'completed'), started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
                duration_seconds REAL NOT NULL, total_bytes INTEGER NOT NULL,
                file_count INTEGER NOT NULL, directory_count INTEGER NOT NULL,
                error_count INTEGER NOT NULL, skipped_count INTEGER NOT NULL,
                coverage TEXT NOT NULL CHECK(coverage IN ('complete', 'limited')),
                created_at TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE directory_snapshots (
                id INTEGER PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES scan_snapshots(id)
                ON DELETE CASCADE, relative_path TEXT NOT NULL, parent_relative_path TEXT,
                name TEXT NOT NULL, direct_bytes INTEGER NOT NULL, subtree_bytes INTEGER NOT NULL,
                file_count INTEGER NOT NULL, directory_count INTEGER NOT NULL,
                coverage TEXT NOT NULL CHECK(coverage IN ('complete', 'limited')),
                UNIQUE(snapshot_id, relative_path))""")
            connection.execute("""CREATE TABLE file_snapshots (
                id INTEGER PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES scan_snapshots(id)
                ON DELETE CASCADE, relative_path TEXT NOT NULL, name TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, mtime TEXT NOT NULL,
                UNIQUE(snapshot_id, relative_path))""")
            connection.execute("CREATE INDEX scan_scope_time ON scan_snapshots(scope_key, completed_at DESC)")
            connection.execute("CREATE INDEX directory_parent ON directory_snapshots(snapshot_id, parent_relative_path)")
            # The UNIQUE constraints also index (snapshot_id, relative_path) for both child tables.
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def save(self, status: dict[str, object], result: ScanResult, root_path: Path) -> str:
        if status["state"] != "completed" or result.cancelled:
            raise ValueError("Only completed scans may be saved.")
        scope_key, scope_label = scope_for_root(str(status["root"]))
        snapshot_id = str(uuid.uuid4())
        coverage = "limited" if result.errors_count or result.skipped_count or result.limited_directories else "complete"
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("""INSERT INTO scan_snapshots VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    snapshot_id, status["scan_id"], scope_key, scope_label, str(root_path),
                    "completed", status["started_at"], status["finished_at"],
                    int(status["elapsed_ms"]) / 1000, result.logical_bytes,
                    result.files_seen, result.dirs_seen, result.errors_count,
                    result.skipped_count, coverage, created_at,
                ))
                connection.executemany("""INSERT INTO directory_snapshots
                    (snapshot_id, relative_path, parent_relative_path, name, direct_bytes,
                     subtree_bytes, file_count, directory_count, coverage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    (snapshot_id, directory.relative_path, directory.parent,
                     directory.relative_path.rsplit("/", 1)[-1] or scope_label,
                     directory.direct_bytes, directory.subtree_bytes, directory.file_count,
                     directory.children_count,
                     "limited" if directory.relative_path in result.limited_directories else "complete")
                    for directory in result.directories.values()
                ))
                connection.executemany("""INSERT INTO file_snapshots
                    (snapshot_id, relative_path, name, size_bytes, mtime) VALUES (?, ?, ?, ?, ?)""", (
                    (snapshot_id, file.relative_path, file.name, file.size_bytes, file.mtime)
                    for file in result.top_files
                ))
                connection.execute("""DELETE FROM scan_snapshots WHERE id IN (
                    SELECT id FROM scan_snapshots WHERE scope_key = ?
                    ORDER BY completed_at DESC, created_at DESC, id DESC
                    LIMIT -1 OFFSET ?)""", (scope_key, RETENTION_PER_SCOPE))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return snapshot_id

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, object]:
        return dict(row)

    def list(self, scope_key: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        with self._connection() as connection:
            if scope_key:
                rows = connection.execute(
                    f"SELECT {SUMMARY_COLUMNS} FROM scan_snapshots WHERE scope_key = ? "
                    "ORDER BY completed_at DESC, created_at DESC LIMIT ?", (scope_key, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT {SUMMARY_COLUMNS} FROM scan_snapshots "
                    "ORDER BY completed_at DESC, created_at DESC LIMIT ?", (limit,),
                ).fetchall()
            return [self._summary(row) for row in rows]

    def get(self, snapshot_id: str) -> dict[str, object]:
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT {SUMMARY_COLUMNS} FROM scan_snapshots WHERE id = ?", (snapshot_id,),
            ).fetchone()
            if row is None:
                raise SnapshotNotFound(snapshot_id)
            return self._summary(row)

    def directories(self, snapshot_id: str, parent: str = "") -> list[dict[str, object]]:
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM directory_snapshots WHERE snapshot_id = ? AND relative_path = ?",
                (snapshot_id, parent),
            ).fetchone()
            if exists is None:
                raise SnapshotNotFound(snapshot_id)
            rows = connection.execute("""SELECT relative_path, parent_relative_path, name,
                direct_bytes, subtree_bytes, file_count, directory_count, coverage
                FROM directory_snapshots WHERE snapshot_id = ? AND parent_relative_path = ?
                ORDER BY subtree_bytes DESC, relative_path""", (snapshot_id, parent)).fetchall()
            return [dict(row) for row in rows]

    def compare(self, base_id: str, target_id: str) -> dict[str, object]:
        with self._connection() as connection:
            def summary(snapshot_id: str) -> dict[str, object]:
                row = connection.execute(
                    f"SELECT {SUMMARY_COLUMNS} FROM scan_snapshots WHERE id = ?", (snapshot_id,),
                ).fetchone()
                if row is None:
                    raise SnapshotNotFound(snapshot_id)
                return self._summary(row)

            base = summary(base_id)
            target = summary(target_id)
            if base["scope_key"] != target["scope_key"]:
                raise SnapshotScopeMismatch("SNAPSHOT_SCOPE_MISMATCH")

            def rows(table: str, snapshot_id: str) -> list[dict[str, object]]:
                # Table names are fixed call-site constants, never user input.
                return [dict(row) for row in connection.execute(
                    f"SELECT * FROM {table} WHERE snapshot_id = ?", (snapshot_id,),
                )]

            directory_comparison = compare_directories(
                rows("directory_snapshots", base_id), rows("directory_snapshots", target_id),
            )
            file_comparison = compare_top_files(
                rows("file_snapshots", base_id), rows("file_snapshots", target_id),
            )
            return {
                "base_snapshot": base,
                "target_snapshot": target,
                "total_bytes_delta": int(target["total_bytes"]) - int(base["total_bytes"]),
                "total_bytes_delta_ratio": delta_ratio(int(base["total_bytes"]), int(target["total_bytes"])),
                "file_count_delta": int(target["file_count"]) - int(base["file_count"]),
                "directory_count_delta": int(target["directory_count"]) - int(base["directory_count"]),
                "comparison_coverage_limited": any(
                    item["coverage"] != "complete" or item["error_count"] or item["skipped_count"]
                    for item in (base, target)
                ),
                **directory_comparison,
                **file_comparison,
                "file_comparison_scope": "top_k_only",
            }


snapshot_store = SnapshotStore()
